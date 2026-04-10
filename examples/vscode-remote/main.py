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
Nginx reverse proxy with SSL termination maps /{port}/ to each instance.

Bridge/host mode is auto-detected from the server-returned endpoint format:
  host mode:   127.0.0.1:8443             -> nginx proxies /8443/ -> http://127.0.0.1:8443/
  bridge mode: 127.0.0.1:55002/proxy/8443  -> nginx proxies /8443/ -> http://127.0.0.1:55002/proxy/8443/

Usage:
    # Setup (one-time)
    bash examples/vscode-remote/setup.sh

    # Run all groups (nginx+SSL on by default)
    uv run python examples/vscode-remote/main.py --groups groups.yaml --external-ip 165.245.138.159

    # Run a single group
    uv run python examples/vscode-remote/main.py --groups groups.yaml --group alpha --external-ip 165.245.138.159

    # Run with per-user passwords
    uv run python examples/vscode-remote/main.py --groups groups.yaml --secure --external-ip 165.245.138.159

    # Run without nginx (direct HTTP access)
    uv run python examples/vscode-remote/main.py --no-nginx

    # Cleanup all nginx configs
    uv run python examples/vscode-remote/main.py --cleanup
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
    upstream_url: str
    password: Optional[str] = None


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


def parse_endpoint(endpoint_str: str) -> tuple[int, str]:
    """Parse the server-returned endpoint to extract the port and upstream URL.

    The endpoint string IS the proxy_pass target (minus the http:// prefix).
    The port after the IP is used for the nginx location path.

    Examples:
      "127.0.0.1:8443"             -> (8443, "127.0.0.1:8443")
      "127.0.0.1:55002/proxy/8443" -> (55002, "127.0.0.1:55002/proxy/8443")

    Returns:
        (port, upstream_url)
    """
    host_port_part = endpoint_str.split("/", 1)[0]
    if ":" in host_port_part:
        port = int(host_port_part.rsplit(":", 1)[1])
    else:
        port = 80
    return port, endpoint_str


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
    secure: bool = False,
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
    endpoint_port, upstream_url = parse_endpoint(endpoint_str)
    network_mode = "bridge" if "/" in endpoint_str else "host"
    print(
        f"[{user.label}] Endpoint: {endpoint_str} "
        f"(detected {network_mode} mode)"
    )

    workspace_path = f"/workspace/{user.workspace}"

    password = None
    auth_flag = "--auth none"
    if secure:
        password = generate_password()
        auth_flag = "--auth password"

    mkdir_cmd = f"mkdir -p {workspace_path}"
    await sandbox.commands.run(mkdir_cmd)

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
        password_cmd = f"echo '{password}' > /tmp/code-server-password"
        await sandbox.commands.run(password_cmd)

    return SandboxInstance(
        user=user,
        port=endpoint_port,
        sandbox=sandbox,
        endpoint=endpoint_str,
        upstream_url=upstream_url,
        password=password,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run VS Code sandbox instances with nginx SSL reverse proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all groups with nginx SSL (default)
  uv run python examples/vscode-remote/main.py --groups groups.yaml --external-ip 165.245.138.159

  # Run a single group
  uv run python examples/vscode-remote/main.py --groups groups.yaml --group alpha --external-ip 1.2.3.4

  # With per-user passwords
  uv run python examples/vscode-remote/main.py --groups groups.yaml --secure --external-ip 1.2.3.4

  # Direct HTTP without nginx
  uv run python examples/vscode-remote/main.py --no-nginx

  # Cleanup all nginx configs
  uv run python examples/vscode-remote/main.py --cleanup
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
        "--secure",
        action="store_true",
        default=False,
        help="Enable per-user password authentication for code-server",
    )
    parser.add_argument(
        "--external-ip",
        type=str,
        default=None,
        help="External IP address for SSL cert SAN and displayed URLs",
    )
    parser.add_argument(
        "--ssl-dir",
        type=str,
        default="/etc/nginx/ssl",
        help="Directory to store SSL certificates (default: /etc/nginx/ssl)",
    )
    parser.add_argument(
        "--no-nginx",
        action="store_true",
        default=False,
        help="Disable nginx reverse proxy (use direct HTTP access)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        default=False,
        help="Remove all sandbox nginx configs and reload, then exit",
    )

    args = parser.parse_args()

    if args.cleanup:
        nginx_gen = NginxConfigGenerator()
        nginx_gen.cleanup_all()
        print("Cleanup complete.")
        return

    use_nginx = not args.no_nginx

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
    print(f"  Port range: {port_range}")
    print(f"  Secure: {'Yes (per-user passwords)' if args.secure else 'No (--auth none)'}")
    print(f"  Nginx: {'Yes (HTTPS)' if use_nginx else 'No (direct HTTP)'}")
    if args.external_ip:
        print(f"  External IP: {args.external_ip}")
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
    nginx_gen: Optional[NginxConfigGenerator] = None

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
                    secure=args.secure,
                )
            )

        instances = list(await asyncio.gather(*tasks))

        if use_nginx:
            nginx_gen = NginxConfigGenerator()
            nginx_gen._remove_default_site()

            ssl_gen = SSLCertificateGenerator(output_dir=args.ssl_dir)
            cert_path, key_path = ssl_gen.generate_server_cert(
                server_ip=args.external_ip,
            )

            for inst in instances:
                config_path = nginx_gen.generate_port_config(
                    port=inst.port,
                    upstream_url=inst.upstream_url,
                    cert_path=cert_path,
                    key_path=key_path,
                    server_name=args.external_ip or "_",
                )
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

            if use_nginx:
                ext_ip = args.external_ip or "localhost"
                url = f"https://{ext_ip}/{inst.port}/"
            else:
                url = f"http://{inst.upstream_url}/"

            print(f"    {inst.user.username}:")
            print(f"      URL: {url}")
            print(f"      Workspace: /workspace/{inst.user.workspace}")
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

        if use_nginx:
            nginx_gen = NginxConfigGenerator()
            try:
                nginx_gen.cleanup_all()
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
