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

Runs multiple VS Code sandbox instances, each reverse-proxied through nginx
with its own self-signed SSL certificate. Certs are generated on the host
via openssl (no pip dependencies). code-server always runs HTTP inside
containers; nginx terminates SSL.

Usage:
    # Setup (one-time)
    bash examples/vscode-remote/setup.sh

    # Run 3 instances with nginx + auto-generated SSL
    uv run python examples/vscode-remote/main.py --instances 3 --use-nginx

    # Run single instance, host mode (port 8443)
    uv run python examples/vscode-remote/main.py --instances 1 --use-nginx --mode host
"""

import argparse
import asyncio
import os
import random
import re
import string
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts

from nginx_config import NginxConfigGenerator
from ssl_cert import SSLCertificateGenerator


def _generate_random_string(length: int = 8) -> str:
    """Generate a random alphanumeric string for URL path obfuscation."""
    characters = string.ascii_lowercase + string.digits
    return "".join(random.choice(characters) for _ in range(length))


@dataclass
class SandboxInstance:
    """Represents a single VS Code sandbox instance."""

    instance_id: int
    workspace: str
    port: int
    sandbox: Sandbox
    endpoint: str
    https: bool = False
    cert_path: Optional[str] = None
    key_path: Optional[str] = None
    nginx_config_path: Optional[str] = None
    url_path: Optional[str] = None  # URI path component e.g. /8443/ or /abc12345/


def _required_env(name: str) -> str:
    """Get a required environment variable or raise an error."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


async def _print_logs(label: str, execution) -> None:
    """Print logs from a sandbox execution."""
    for msg in execution.logs.stdout:
        print(f"[{label} stdout] {msg.text}")
    for msg in execution.logs.stderr:
        print(f"[{label} stderr] {msg.text}")
    if execution.error:
        print(f"[{label} error] {execution.error.name}: {execution.error.value}")


async def create_instance(
    instance_id: int,
    workspace: str,
    port: int,
    config: ConnectionConfig,
    image: str,
    python_version: str,
    timeout: timedelta,
    mode: str = "bridge",
    use_nginx: bool = False,
    nginx_domain: str = "localhost",
    ssl_dir: str = "/etc/nginx/ssl",
    server_ip: Optional[str] = None,
) -> SandboxInstance:
    """Create a single VS Code sandbox instance with nginx SSL termination.

    Args:
        instance_id: Instance index
        workspace: Workspace directory name inside container
        port: Port code-server listens on inside the container
        config: OpenSandbox connection configuration
        image: Docker image name
        python_version: Python version to inject into container env
        mode: 'bridge' (random port 40000-60000) or 'host' (sequential from 8443)
        use_nginx: If True, generate nginx config + per-instance SSL cert
        nginx_domain: Base domain for subdomain-based routing
        ssl_dir: Directory to store generated SSL certificates
        server_ip: Server IP to embed in SAN (fixes SW SSL errors)

    Returns:
        SandboxInstance with endpoint, cert paths, and nginx config info
    """
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
    is_eip = bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", endpoint_host))

    if is_eip and server_ip is None:
        server_ip = endpoint_host
        print(f"[Instance {instance_id}] Detected EIP: {server_ip}")

    if mode == "host":
        upstream_host = "127.0.0.1"
        upstream_port = port
        upstream_path = ""
    else:
        parts = endpoint_str.split("/", 1)
        upstream_path = f"/{parts[1]}" if len(parts) > 1 else ""
        host_port_part = parts[0]
        if ":" in host_port_part:
            upstream_port = int(host_port_part.rsplit(":", 1)[1])
        else:
            upstream_port = 80
        upstream_host = "127.0.0.1"

    workspace_path = f"/workspace/{workspace}"

    code_server_cmd = (
        f"code-server --bind-addr 0.0.0.0:{port} "
        f"--auth none "
        f"--disable-telemetry "
        f"{workspace_path}"
    )
    print(f"[Instance {instance_id}] Starting code-server (HTTP) on port {port}")

    start_exec = await sandbox.commands.run(
        code_server_cmd,
        opts=RunCommandOpts(background=True),
    )
    await _print_logs(f"code-server-{instance_id}", start_exec)

    url_path = None
    nginx_config_path = None
    cert_path = None
    key_path = None

    if use_nginx:
        print(f"[Nginx] Generating config for instance {instance_id} (port={port})...")
        nginx_gen = NginxConfigGenerator()
        ssl_gen = SSLCertificateGenerator(output_dir=ssl_dir)

        if mode == "host":
            url_path = f"/{port}/"
            cert_path, key_path = ssl_gen.generate_cert_for_port(
                port=port,
                server_ip=server_ip,
            )
            server_name = endpoint_host or "localhost"
        else:
            url_path = f"/{_generate_random_string()}/"
            subdomain = ssl_gen.generate_random_subdomain(base_domain=nginx_domain)
            server_name = subdomain
            cert_path, key_path = ssl_gen.generate_cert_for_subdomain(
                subdomain=subdomain,
                server_ip=server_ip,
            )

        nginx_config_path = nginx_gen.generate_config(
            server_name=server_name,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            upstream_path=upstream_path,
            use_https=True,
            cert_path=cert_path,
            key_path=key_path,
            location_path=url_path,
        )
        nginx_gen.enable_config(nginx_config_path)
        nginx_gen.reload_nginx()
        print(f"[Nginx] Instance {instance_id} ready at https://{server_name}{url_path}")

    return SandboxInstance(
        instance_id=instance_id,
        workspace=workspace,
        port=port,
        sandbox=sandbox,
        endpoint=endpoint.endpoint,
        https=use_nginx,
        cert_path=cert_path,
        key_path=key_path,
        nginx_config_path=nginx_config_path,
        url_path=url_path,
    )


async def run_instances(
    instances: int,
    workspace: str,
    start_port: int,
    sandbox_timeout: timedelta,
    domain: str,
    api_key: Optional[str],
    image: str,
    python_version: str,
    mode: str = "bridge",
    use_nginx: bool = False,
    nginx_domain: str = "localhost",
    ssl_dir: str = "/etc/nginx/ssl",
) -> list[SandboxInstance]:
    """Run multiple VS Code sandbox instances concurrently."""
    config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=60),
    )

    tasks = []
    for i in range(instances):
        tasks.append(
            create_instance(
                instance_id=i,
                workspace=workspace,
                port=start_port + i,
                config=config,
                image=image,
                python_version=python_version,
                timeout=sandbox_timeout,
                mode=mode,
                use_nginx=use_nginx,
                nginx_domain=nginx_domain,
                ssl_dir=ssl_dir,
            )
        )

    instances_list = await asyncio.gather(*tasks)
    return list(instances_list)


async def main() -> None:
    """Main entry point for the multi-instance VS Code example."""
    parser = argparse.ArgumentParser(
        description="Run multiple VS Code sandbox instances with nginx SSL termination",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Setup prerequisites (one-time)
  bash examples/vscode-remote/setup.sh

  # Run 3 instances with auto-generated nginx + SSL (bridge mode)
  uv run python examples/vscode-remote/main.py --instances 3 --use-nginx

  # Run 1 instance in host mode (port -> /port/ URI path)
  uv run python examples/vscode-remote/main.py --instances 1 --use-nginx --mode host

  # Custom SSL output directory
  uv run python examples/vscode-remote/main.py --instances 1 --use-nginx --ssl-dir ./certs

  # Run without nginx (direct HTTP access)
  uv run python examples/vscode-remote/main.py --instances 2
        """,
    )

    parser.add_argument(
        "--instances", type=int, default=1,
        help="Number of concurrent sandbox instances (default: 1)",
    )
    parser.add_argument(
        "--workspace", type=str, default="default",
        help="Workspace name for all instances (default: default)",
    )
    parser.add_argument(
        "--port", type=int, default=8443,
        help="Starting port for code-server instances (default: 8443)",
    )
    parser.add_argument(
        "--timeout", type=int, default=10,
        help="Timeout in minutes to keep sandboxes alive (default: 10)",
    )
    parser.add_argument(
        "--domain", type=str, default=None,
        help="Sandbox domain (default: localhost:8080)",
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="Sandbox API key (optional)",
    )
    parser.add_argument(
        "--image", type=str, default=None,
        help="Docker image for sandbox (default: opensandbox/vscode:latest)",
    )
    parser.add_argument(
        "--python-version", type=str, default="3.11",
        help="Python version for the sandbox (default: 3.11)",
    )
    parser.add_argument(
        "--mode", type=str, choices=["bridge", "host"], default="bridge",
        help="Network mode: bridge (random port, subdomain URI) or host (sequential /port/ URI)",
    )
    parser.add_argument(
        "--use-nginx", action="store_true", default=False,
        help="Use nginx reverse proxy with per-instance SSL certs (auto-generated via openssl)",
    )
    parser.add_argument(
        "--nginx-domain", type=str, default="localhost",
        help="Base domain for nginx subdomains (bridge mode, default: localhost)",
    )
    parser.add_argument(
        "--ssl-dir", type=str, default="/etc/nginx/ssl",
        help="Directory to store generated SSL certificates (default: /etc/nginx/ssl)",
    )
    parser.add_argument(
        "--server-ip", type=str, default=None,
        help="Server IP address for SAN in certs (fixes Service Worker SSL errors)",
    )

    args = parser.parse_args()

    if args.instances < 1:
        print("Error: Number of instances must be at least 1")
        sys.exit(1)

    if args.instances > 100:
        print("Warning: Running more than 100 instances may cause resource issues")

    domain = args.domain or os.getenv("SANDBOX_DOMAIN", "localhost:8080")
    api_key = args.api_key or os.getenv("SANDBOX_API_KEY")
    image = args.image or os.getenv("SANDBOX_IMAGE", "opensandbox/vscode:latest")
    python_version = args.python_version or os.getenv("PYTHON_VERSION", "3.11")

    print(f"Starting {args.instances} VS Code sandbox instance(s)...")
    print(f"  Domain: {domain}")
    print(f"  Image: {image}")
    print(f"  Workspace: {args.workspace}")
    print(f"  Mode: {args.mode}")
    print(f"  Port range: {args.port} - {args.port + args.instances - 1}")
    print(f"  Nginx: {'Yes (auto SSL)' if args.use_nginx else 'No (direct HTTP)'}")
    print(f"  SSL dir: {args.ssl_dir}")
    print()

    try:
        sandbox_timeout = timedelta(minutes=args.timeout)

        instances_list = await run_instances(
            instances=args.instances,
            workspace=args.workspace,
            start_port=args.port,
            sandbox_timeout=sandbox_timeout,
            domain=domain,
            api_key=api_key,
            image=image,
            python_version=python_version,
            mode=args.mode,
            use_nginx=args.use_nginx,
            nginx_domain=args.nginx_domain,
            ssl_dir=args.ssl_dir,
        )

        print("\n" + "=" * 60)
        print("VS Code Web Endpoints")
        print("=" * 60)
        for instance in instances_list:
            protocol = "https" if instance.https else "http"
            print(f"\n  Instance {instance.instance_id + 1}:")
            print(f"    Workspace: {instance.workspace}")
            print(f"    Port: {instance.port}")
            if instance.nginx_config_path and instance.url_path:
                config_filename = Path(instance.nginx_config_path).name
                server_name = config_filename.replace("sandbox-", "").replace("-", ".")
                print(f"    URL: {protocol}://{server_name}{instance.url_path}")
            else:
                print(f"    URL: {protocol}://{instance.endpoint}/")
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
        print("\nCleaning up sandbox instances...")

        if args.use_nginx:
            print("\nCleaning up nginx configurations...")
            nginx_gen = NginxConfigGenerator()
            for instance in instances_list:
                if instance.nginx_config_path:
                    try:
                        nginx_gen.delete_config(instance.nginx_config_path)
                    except Exception as e:
                        print(f"  Note: Failed to delete nginx config: {e}")
            try:
                nginx_gen.reload_nginx()
            except Exception as e:
                print(f"  Note: Failed to reload nginx: {e}")

        for instance in instances_list:
            try:
                await instance.sandbox.kill()
            except Exception as e:
                print(
                    f"  Note: Sandbox {instance.instance_id + 1} may have already been "
                    f"terminated: {e}"
                )
        print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
