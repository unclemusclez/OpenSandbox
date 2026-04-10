# Copyright 2025 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
VS Code Remote - Multi-Instance Hackathon Example

Runs multiple VS Code sandbox instances driven by a groups.yaml config.
Each user gets their own sandbox with workspace at /workspace/{group}/{username}.
An nginx reverse proxy maps each instance by port number: /{port}/.

Usage:
    # Setup (one-time)
    bash examples/vscode-remote/setup.sh

    # Run all groups from groups.yaml
    uv run python examples/vscode-remote/main.py --groups groups.yaml

    # Run a single group
    uv run python examples/vscode-remote/main.py --groups groups.yaml --group alpha

    # Run with per-user passwords (secure mode)
    uv run python examples/vscode-remote/main.py --groups groups.yaml --secure

    # Run without groups (single instance, like examples/vscode/main.py)
    uv run python examples/vscode-remote/main.py
"""

import argparse
import asyncio
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import yaml

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts

from nginx_config import NginxConfigGenerator
from ssl_cert import SSLCertificateGenerator


@dataclass
class UserInfo:
    group: str
    username: str

    @property
    def workspace(self) -> str:
        return f"{self.group}/{self.username}"

    @property
    def label(self) -> str:
        return f"{self.group}/{self.username}"


@dataclass
class SandboxInstance:
    user: UserInfo
    port: int
    sandbox: Sandbox
    endpoint: str
    url_path: str
    upstream_host: str
    upstream_port: int
    upstream_path: str
    password: Optional[str] = None
    nginx_config_path: Optional[str] = None
    cert_path: Optional[str] = None
    key_path: Optional[str] = None


def load_groups(groups_file: str, group_filter: Optional[str] = None) -> list[UserInfo]:
    with open(groups_file) as f:
        data = yaml.safe_load(f)

    groups = data.get("groups", {})
    users: list[UserInfo] = []

    for group_name, group_data in groups.items():
        if group_filter and group_name != group_filter:
            continue
        for username in group_data.get("users", []):
            users.append(UserInfo(group=group_name, username=username))

    return users


def generate_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)


def parse_endpoint(
    endpoint_str: str, mode: str, port: int
) -> tuple[str, int, str]:
    if mode == "host":
        return "127.0.0.1", port, ""

    parts = endpoint_str.split("/", 1)
    upstream_path = f"/{parts[1]}" if len(parts) > 1 else ""
    host_port_part = parts[0]
    if ":" in host_port_part:
        upstream_port = int(host_port_part.rsplit(":", 1)[1])
    else:
        upstream_port = 80
    return "127.0.0.1", upstream_port, upstream_path


async def _print_logs(label: str, execution) -> None:
    for msg in execution.logs.stdout:
        print(f"[{label} stdout] {msg.text}")
    for msg in execution.logs.stderr:
        print(f"[{label} stderr] {msg.text}")
    if execution.error:
        print(f"[{label} error] {execution.error.name}: {execution.error.value}")


async def create_instance(
    user: UserInfo,
    port: int,
    config: ConnectionConfig,
    image: str,
    python_version: str,
    timeout: timedelta,
    mode: str = "host",
    secure: bool = False,
    ssl_dir: str = "/etc/nginx/ssl",
    server_ip: Optional[str] = None,
) -> SandboxInstance:
    env = {"PYTHON_VERSION": python_version}

    sandbox = await Sandbox.create(
        image,
        connection_config=config,
        env=env,
        timeout=timeout,
    )

    endpoint = await sandbox.get_endpoint(port)
    endpoint_str = endpoint.endpoint
    endpoint_host = endpoint_str.split(":")[0]

    is_eip = (
        endpoint_host.replace(".", "").isdigit()
        and len(endpoint_host.split(".")) == 4
    )
    if is_eip and server_ip is None:
        server_ip = endpoint_host
        print(f"[{user.label}] Detected EIP: {server_ip}")

    upstream_host, upstream_port, upstream_path = parse_endpoint(
        endpoint_str, mode, port
    )

    workspace_path = f"/workspace/{user.workspace}"

    password = None
    auth_flag = "--auth none"
    if secure:
        password = generate_password()
        auth_flag = "--auth password"

    code_server_cmd = (
        f"code-server --bind-addr 0.0.0.0:{port} "
        f"{auth_flag} "
        f"--disable-telemetry "
        f"{workspace_path}"
    )
    print(f"[{user.label}] Starting code-server on port {port}")

    start_exec = await sandbox.commands.run(
        code_server_cmd,
        opts=RunCommandOpts(background=True),
    )
    await _print_logs(user.label, start_exec)

    if secure and password:
        mkdir_cmd = (
            f"mkdir -p {workspace_path} && "
            f"CONFIG_DIR=$(dirname $(code-server --list-extensions 2>/dev/null | head -1 || echo /tmp/config)) && "
            f"mkdir -p /tmp/code-server && "
            f"echo '{password}' > /tmp/code-server/password"
        )
        await sandbox.commands.run(mkdir_cmd)
        print(f"[{user.label}] Password set (saved to /tmp/code-server/password)")

    cert_path = None
    key_path = None

    if server_ip or mode == "host":
        ssl_gen = SSLCertificateGenerator(output_dir=ssl_dir)
        cert_path, key_path = ssl_gen.generate_cert_for_port(
            port=port,
            server_ip=server_ip,
        )

    return SandboxInstance(
        user=user,
        port=port,
        sandbox=sandbox,
        endpoint=endpoint_str,
        url_path=f"/{port}/",
        upstream_host=upstream_host,
        upstream_port=upstream_port,
        upstream_path=upstream_path,
        password=password,
        cert_path=cert_path,
        key_path=key_path,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run VS Code sandbox instances with nginx reverse proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all groups
  uv run python examples/vscode-remote/main.py --groups groups.yaml

  # Run a single group
  uv run python examples/vscode-remote/main.py --groups groups.yaml --group alpha

  # Run with secure per-user passwords
  uv run python examples/vscode-remote/main.py --groups groups.yaml --secure

  # Single instance without groups (like examples/vscode/main.py)
  uv run python examples/vscode-remote/main.py
        """,
    )

    parser.add_argument(
        "--groups",
        type=str,
        default=None,
        help="Path to groups.yaml file",
    )
    parser.add_argument(
        "--group",
        type=str,
        default=None,
        help="Run only this group from groups.yaml",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help="Starting port for code-server instances (default: 8443)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Timeout in minutes to keep sandboxes alive (default: 10)",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Sandbox domain (default: localhost:8080)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Sandbox API key (optional)",
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="Docker image for sandbox (default: opensandbox/vscode:latest)",
    )
    parser.add_argument(
        "--python-version",
        type=str,
        default="3.11",
        help="Python version for the sandbox (default: 3.11)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["bridge", "host"],
        default="host",
        help="Network mode matching server config: host or bridge (default: host)",
    )
    parser.add_argument(
        "--secure",
        action="store_true",
        default=False,
        help="Enable per-user password authentication for code-server",
    )
    parser.add_argument(
        "--ssl-dir",
        type=str,
        default="/etc/nginx/ssl",
        help="Directory to store generated SSL certificates (default: /etc/nginx/ssl)",
    )
    parser.add_argument(
        "--server-ip",
        type=str,
        default=None,
        help="Server IP for SSL cert SAN (fixes Service Worker SSL errors)",
    )
    parser.add_argument(
        "--use-nginx",
        action="store_true",
        default=False,
        help="Generate nginx reverse proxy config with SSL termination",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        default=False,
        help="Remove all previously generated sandbox nginx configs and reload, then exit",
    )

    args = parser.parse_args()

    if args.cleanup:
        nginx_gen = NginxConfigGenerator()
        nginx_gen.cleanup_all()
        print("Cleanup complete.")
        return

    domain = args.domain or os.getenv("SANDBOX_DOMAIN", "localhost:8080")
    api_key = args.api_key or os.getenv("SANDBOX_API_KEY")
    image = args.image or os.getenv("SANDBOX_IMAGE", "opensandbox/vscode:latest")
    python_version = args.python_version or os.getenv("PYTHON_VERSION", "3.11")

    users: list[UserInfo]
    if args.groups:
        users = load_groups(args.groups, group_filter=args.group)
        if not users:
            print("Error: No users found in groups config")
            sys.exit(1)
        if args.group and not any(u.group == args.group for u in users):
            print(f"Error: Group '{args.group}' not found in {args.groups}")
            sys.exit(1)
    else:
        users = [UserInfo(group="default", username="workspace")]

    total = len(users)
    port_range = f"{args.port} - {args.port + total - 1}"

    print(f"Starting {total} VS Code sandbox instance(s)...")
    print(f"  Domain: {domain}")
    print(f"  Image: {image}")
    print(f"  Mode: {args.mode}")
    print(f"  Port range: {port_range}")
    print(f"  Secure: {'Yes (per-user passwords)' if args.secure else 'No (--auth none)'}")
    print(f"  Nginx: {'Yes' if args.use_nginx else 'No'}")
    if args.groups:
        print(f"  Groups file: {args.groups}")
        if args.group:
            print(f"  Group filter: {args.group}")
    print()

    config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=60),
    )
    sandbox_timeout = timedelta(minutes=args.timeout)

    instances: list[SandboxInstance] = []

    try:
        tasks = []
        for i, user in enumerate(users):
            tasks.append(
                create_instance(
                    user=user,
                    port=args.port + i,
                    config=config,
                    image=image,
                    python_version=python_version,
                    timeout=sandbox_timeout,
                    mode=args.mode,
                    secure=args.secure,
                    ssl_dir=args.ssl_dir,
                    server_ip=args.server_ip,
                )
            )

        instances = list(await asyncio.gather(*tasks))

        if args.use_nginx:
            nginx_gen = NginxConfigGenerator()
            server_name = args.server_ip or "localhost"
            for inst in instances:
                if not inst.cert_path or not inst.key_path:
                    print(f"[Nginx] Skipping port {inst.port}: no SSL cert")
                    continue

                upstream_path = inst.upstream_path if inst.upstream_path else "/"
                config_path = nginx_gen.generate_port_config(
                    port=inst.port,
                    server_name=server_name,
                    upstream_host=inst.upstream_host,
                    upstream_port=inst.upstream_port,
                    upstream_path=upstream_path,
                    cert_path=inst.cert_path,
                    key_path=inst.key_path,
                )
                inst.nginx_config_path = config_path
                nginx_gen.enable_config(config_path)

            nginx_gen.test_config()
            nginx_gen.reload_nginx()

        print("\n" + "=" * 70)
        print("VS Code Web Endpoints")
        print("=" * 70)

        current_group: Optional[str] = None
        for inst in instances:
            if inst.user.group != current_group:
                current_group = inst.user.group
                print(f"\n  Group: {current_group}")

            protocol = "https" if args.use_nginx else "http"
            server_host = args.server_ip or "localhost"

            if args.use_nginx:
                url = f"{protocol}://{server_host}{inst.url_path}"
            else:
                url = f"http://{inst.endpoint}/"

            print(f"    {inst.user.username}:")
            print(f"      URL: {url}")
            print(f"      Workspace: /workspace/{inst.user.workspace}")
            print(f"      Port: {inst.port}")
            if inst.password:
                print(f"      Password: {inst.password}")

        print()
        print(
            f"Keeping sandboxes alive for {args.timeout} minutes. "
            f"Press Ctrl+C to exit sooner."
        )

        try:
            await asyncio.sleep(args.timeout * 60)
        except KeyboardInterrupt:
            print("\nStopping...")

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        print("\nCleaning up...")

        if args.use_nginx and instances:
            nginx_gen = NginxConfigGenerator()
            try:
                for inst in instances:
                    if inst.nginx_config_path:
                        try:
                            nginx_gen.delete_config(inst.nginx_config_path)
                        except Exception as e:
                            print(f"  Note: Failed to delete nginx config for port {inst.port}: {e}")
                try:
                    nginx_gen.reload_nginx()
                except Exception as e:
                    print(f"  Note: Failed to reload nginx after cleanup: {e}")
            except Exception as e:
                print(f"  Note: Nginx cleanup error: {e}")

        for inst in instances:
            try:
                await inst.sandbox.kill()
            except Exception as e:
                print(f"  Note: Sandbox {inst.user.label} may already be terminated: {e}")

        print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
