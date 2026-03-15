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
VS Code Remote - Multi-Instance Example with HTTPS Support

This example demonstrates how to run multiple VS Code sandbox instances
simultaneously, each with its own workspace and code-server instance.

HTTPS Support:
    - Uses mkcert for local development certificates
    - Per-sandbox or wildcard certificates
    - HTTPS on port 44772 (or custom port)

Usage:
    uv run python examples/vscode-remote/main.py --instances 3 --workspace myproject --https

Features:
    - Multiple concurrent sandbox instances
    - Unique port allocation per instance
    - Workspace separation for each instance
    - Configurable timeout and image settings
    - HTTPS support with mkcert certificates
"""

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts


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


async def _inject_certificate(
    sandbox: Sandbox,
    host_cert_path: str,
    host_key_path: str,
) -> tuple[str, str]:
    """
    Inject certificate and key files into the container filesystem.

    Reads the certificate files from the host and writes them to
    /tmp/ directory inside the container for code-server to use.

    Args:
        sandbox: The sandbox instance
        host_cert_path: Path to certificate file on the host
        host_key_path: Path to key file on the host

    Returns:
        Tuple of (container_cert_path, container_key_path)
    """
    # Read certificate files from host
    cert_content = Path(host_cert_path).read_text()
    key_content = Path(host_key_path).read_text()

    # Write certificate to container
    container_cert_path = "/tmp/cert.pem"
    cert_exec = await sandbox.commands.run(
        f"cat > {container_cert_path} << 'EOF'\n{cert_content}\nEOF",
        opts=RunCommandOpts(background=False),
    )
    await _print_logs("inject-cert", cert_exec)

    # Write key to container
    container_key_path = "/tmp/key.pem"
    key_exec = await sandbox.commands.run(
        f"cat > {container_key_path} << 'EOF'\n{key_content}\nEOF",
        opts=RunCommandOpts(background=False),
    )
    await _print_logs("inject-key", key_exec)

    # Set proper permissions on key file
    chmod_exec = await sandbox.commands.run(
        f"chmod 600 {container_key_path}",
        opts=RunCommandOpts(background=False),
    )
    await _print_logs("chmod-key", chmod_exec)

    return container_cert_path, container_key_path


async def create_instance(
    instance_id: int,
    workspace: str,
    port: int,
    config: ConnectionConfig,
    image: str,
    python_version: str,
    timeout: timedelta,
    https: bool = False,
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
    sandbox_id: Optional[str] = None,
    force_https: bool = False,
) -> SandboxInstance:
    """Create a single VS Code sandbox instance."""
    # Inject Python version into container environment
    env = {"PYTHON_VERSION": python_version}

    sandbox = await Sandbox.create(
        image,
        connection_config=config,
        env=env,
        timeout=timeout,
    )

    # Get the endpoint for this instance BEFORE starting code-server
    # This allows us to determine if proxy mode will be used
    print(f"[DEBUG] Instance {instance_id}: Getting endpoint for port {port}")
    print(f"[DEBUG] Instance {instance_id}: connection_config.domain={config.domain}")
    print(
        f"[DEBUG] Instance {instance_id}: connection_config.use_server_proxy={config.use_server_proxy}"
    )
    endpoint = await sandbox.get_endpoint(port)

    # Check if the endpoint host is an IP address (EIP)
    endpoint_host = endpoint.endpoint.split(":")[0]
    print(f"[DEBUG] Instance {instance_id}: endpoint.endpoint = {endpoint.endpoint}")
    print(f"[DEBUG] Instance {instance_id}: endpoint_host = {endpoint_host}")
    print(
        r"[DEBUG] Instance {instance_id}: regex pattern = ^\d{{1,3}}\.\d{{1,3}}\.\d{{1,3}}\.\d{{1,3}}$".format(
            instance_id=instance_id
        )
    )
    is_eip = bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", endpoint_host))
    print(f"[DEBUG] Instance {instance_id}: is_eip = {is_eip}")
    print(
        f"[DEBUG] Instance {instance_id}: https = {https}, force_https = {force_https}"
    )

    # Determine if we will use proxy mode
    use_proxy = False
    if https and is_eip and not force_https:
        use_proxy = True
        print(
            f"[Instance {instance_id}] Notice: Detected EIP usage ({endpoint_host}). "
            "Using server proxy for HTTPS support."
        )
        print(
            f"[Instance {instance_id}]          Use --force-https to use direct EIP connection "
            "(requires certificate matching the EIP)."
        )
        # Update sandbox connection config to use proxy
        print(
            f"[DEBUG] Instance {instance_id}: Creating proxy_config with use_server_proxy=True"
        )
        proxy_config = ConnectionConfig(
            domain=config.domain,
            api_key=config.api_key,
            request_timeout=config.request_timeout,
            use_server_proxy=True,
        )
        print(
            f"[DEBUG] Instance {instance_id}: proxy_config.domain={proxy_config.domain}"
        )
        print(
            f"[DEBUG] Instance {instance_id}: proxy_config.use_server_proxy={proxy_config.use_server_proxy}"
        )
        sandbox._connection_config = proxy_config
        print(
            f"[DEBUG] Instance {instance_id}: Updated sandbox._connection_config.use_server_proxy={sandbox._connection_config.use_server_proxy}"
        )
        endpoint = await sandbox.get_endpoint(port)
        print(
            f"[DEBUG] Instance {instance_id}: New endpoint (proxy) = {endpoint.endpoint}"
        )
    elif https and is_eip and force_https:
        print(
            f"[Instance {instance_id}] Notice: Using direct EIP connection with HTTPS. "
            "Ensure certificate matches {endpoint_host}."
        )

    # Build code-server command
    # IMPORTANT: When using proxy mode, code-server must use HTTP (not HTTPS)
    # because the proxy connects to the sandbox via HTTP internally.
    # HTTPS is handled from client to proxy, not from proxy to sandbox.
    workspace_path = f"/workspace/{workspace}"

    # Determine if code-server should use HTTPS or HTTP
    # When use_proxy=True, always use HTTP for code-server
    # When use_proxy=False, use HTTPS if https flag is set
    use_https_for_code_server = https and not use_proxy

    if use_https_for_code_server:
        # HTTPS mode - inject certificates into container first
        if cert_path and key_path:
            print(f"[Instance {instance_id}] Injecting certificates into container...")
            container_cert_path, container_key_path = await _inject_certificate(
                sandbox, cert_path, key_path
            )
            print(f"[Instance {instance_id}] Certificates injected successfully")
        else:
            raise ValueError(
                f"HTTPS enabled but no certificates provided for instance {instance_id}"
            )

        cert_flag = f"--cert {container_cert_path}"
        key_flag = f"--cert-key {container_key_path}"
        code_server_cmd = (
            f"code-server {cert_flag} {key_flag} "
            f"--bind-addr 0.0.0.0:{port} "
            f"--auth none "
            f"--disable-telemetry "
            f"{workspace_path}"
        )
        print(
            f"[Instance {instance_id}] Starting code-server with HTTPS on port {port}"
        )
    else:
        # HTTP mode (default or when using proxy)
        code_server_cmd = (
            f"code-server --bind-addr 0.0.0.0:{port} "
            f"--auth none "
            f"--disable-telemetry "
            f"{workspace_path}"
        )
        if use_proxy:
            print(
                f"[Instance {instance_id}] Starting code-server with HTTP on port {port} (proxy mode)"
            )
        else:
            print(
                f"[Instance {instance_id}] Starting code-server with HTTP on port {port}"
            )

    start_exec = await sandbox.commands.run(
        code_server_cmd,
        opts=RunCommandOpts(background=True),
    )
    await _print_logs(f"code-server-{instance_id}", start_exec)

    # The actual_https flag indicates what the client sees
    # When using proxy, the client sees HTTPS (proxy handles SSL)
    # but code-server runs with HTTP internally
    actual_https = https
    print(f"[DEBUG] Instance {instance_id}: actual_https = {actual_https}")

    return SandboxInstance(
        instance_id=instance_id,
        workspace=workspace,
        port=port,
        sandbox=sandbox,
        endpoint=endpoint.endpoint,
        https=actual_https,
        cert_path=cert_path,
        key_path=key_path,
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
    https: bool = False,
    cert_path: Optional[str | list[str]] = None,
    key_path: Optional[str | list[str]] = None,
    sandbox_ids: Optional[list[str]] = None,
    force_https: bool = False,
) -> list[SandboxInstance]:
    """Run multiple VS Code sandbox instances concurrently."""
    config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=60),
        # use_server_proxy=True,  # Remove this line to use direct sandbox access with EIP
    )

    # Create all instances concurrently
    tasks = []
    for i in range(instances):
        sandbox_id = (
            f"vscode-{start_port + i}" if sandbox_ids is None else sandbox_ids[i]
        )

        # Determine certificate paths for this instance
        instance_cert_path = None
        instance_key_path = None
        if https:
            if isinstance(cert_path, list):
                instance_cert_path = cert_path[i] if i < len(cert_path) else None
            else:
                instance_cert_path = cert_path

            if isinstance(key_path, list):
                instance_key_path = key_path[i] if i < len(key_path) else None
            else:
                instance_key_path = key_path

        tasks.append(
            create_instance(
                instance_id=i,
                workspace=workspace,
                port=start_port + i,
                config=config,
                image=image,
                python_version=python_version,
                timeout=sandbox_timeout,
                https=https,
                cert_path=instance_cert_path,
                key_path=instance_key_path,
                sandbox_id=sandbox_id,
                force_https=force_https,
            )
        )

    instances_list = await asyncio.gather(*tasks)
    return list(instances_list)


async def main() -> None:
    """Main entry point for the multi-instance VS Code example."""
    parser = argparse.ArgumentParser(
        description="Run multiple VS Code sandbox instances concurrently",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run 3 instances with default settings (HTTP)
  uv run python examples/vscode-remote/main.py --instances 3

  # Run with HTTPS using wildcard certificate
  uv run python examples/vscode-remote/main.py --instances 3 --https \\
    --cert /path/to/localhost.pem --key /path/to/localhost-key.pem

  # Run with per-sandbox certificates
  uv run python examples/vscode-remote/main.py --instances 3 --https \\
    --cert /path/to/sandbox0.pem --key /path/to/sandbox0-key.pem \\
    --cert /path/to/sandbox1.pem --key /path/to/sandbox1-key.pem \\
    --cert /path/to/sandbox2.pem --key /path/to/sandbox2-key.pem

  # Generate certificates first, then run
  uv run python examples/vscode-remote/generate-certs.py
  uv run python examples/vscode-remote/main.py --instances 3 --https \\
    --cert ./certs/localhost.pem --key ./certs/localhost-key.pem
        """,
    )

    parser.add_argument(
        "--https",
        action="store_true",
        default=False,
        help="Use HTTPS (requires --cert and --key flags)",
    )
    parser.add_argument(
        "--cert",
        type=str,
        action="append",
        default=[],
        help="Certificate file path (can be specified multiple times for per-sandbox certs)",
    )
    parser.add_argument(
        "--key",
        type=str,
        action="append",
        default=[],
        help="Certificate key file path (can be specified multiple times for per-sandbox certs)",
    )
    parser.add_argument(
        "--instances",
        type=int,
        default=1,
        help="Number of concurrent sandbox instances (default: 1)",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default="default",
        help="Workspace name for all instances (default: default)",
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
        "--force-https",
        action="store_true",
        default=False,
        help="Force HTTPS even with EIP (requires certificate matching EIP hostname)",
    )

    args = parser.parse_args()

    # Validate HTTPS arguments
    if args.https:
        if not args.cert or not args.key:
            print("Error: --https requires --cert and --key flags")
            print()
            print("Example with wildcard certificate:")
            print(
                "  uv run python examples/vscode-remote/main.py --instances 3 --https \\"
            )
            print("    --cert ./certs/localhost.pem --key ./certs/localhost-key.pem")
            print()
            print("Generate certificates first:")
            print("  uv run python examples/vscode-remote/generate-certs.py")
            sys.exit(1)

        # Check if we have per-sandbox certs or wildcard cert
        if len(args.cert) == 1 and len(args.key) == 1:
            # Wildcard certificate - use same cert for all instances
            cert_path = args.cert[0]
            key_path = args.key[0]
            if not Path(cert_path).exists():
                print(f"Error: Certificate file not found: {cert_path}")
                sys.exit(1)
            if not Path(key_path).exists():
                print(f"Error: Key file not found: {key_path}")
                sys.exit(1)
            print(f"Using wildcard certificate: {cert_path}")
        else:
            # Per-sandbox certificates
            if len(args.cert) != args.instances:
                print(
                    f"Error: Expected {args.instances} certificate pairs for {args.instances} instances"
                )
                print(f"Got {len(args.cert)} certificate(s)")
                sys.exit(1)
            if len(args.key) != args.instances:
                print(
                    f"Error: Expected {args.instances} key pairs for {args.instances} instances"
                )
                print(f"Got {len(args.key)} key(s)")
                sys.exit(1)
            for i, (cert, key) in enumerate(zip(args.cert, args.key)):
                if not Path(cert).exists():
                    print(f"Error: Certificate file not found: {cert}")
                    sys.exit(1)
                if not Path(key).exists():
                    print(f"Error: Key file not found: {key}")
                    sys.exit(1)
            print(f"Using per-sandbox certificates for {args.instances} instances")

    # Validate arguments
    if args.instances < 1:
        print("Error: Number of instances must be at least 1")
        sys.exit(1)

    if args.instances > 100:
        print("Warning: Running more than 100 instances may cause resource issues")

    # Get configuration from environment or arguments
    domain = args.domain or os.getenv("SANDBOX_DOMAIN", "localhost:8080")
    api_key = args.api_key or os.getenv("SANDBOX_API_KEY")
    image = args.image or os.getenv(
        "SANDBOX_IMAGE",
        "opensandbox/vscode:latest",
    )
    python_version = args.python_version or os.getenv("PYTHON_VERSION", "3.11")

    print(f"Starting {args.instances} VS Code sandbox instance(s)...")
    print(f"  Domain: {domain}")
    print(f"  Image: {image}")
    print(f"  Workspace: {args.workspace}")
    print(f"  Port range: {args.port} - {args.port + args.instances - 1}")
    print(f"  Timeout: {args.timeout} minutes")
    print(f"  HTTPS: {'Yes' if args.https else 'No'}")
    if args.https:
        if len(args.cert) == 1:
            print(f"  Certificate: {args.cert[0]} (wildcard)")
        else:
            print(f"  Certificates: {len(args.cert)} per-sandbox certs")
    print()

    try:
        # Convert timeout to timedelta
        sandbox_timeout = timedelta(minutes=args.timeout)

        # Prepare certificate paths
        cert_paths = (
            args.cert if len(args.cert) > 1 else (args.cert[0] if args.cert else None)
        )
        key_paths = (
            args.key if len(args.key) > 1 else (args.key[0] if args.key else None)
        )

        # Run all instances concurrently
        instances_list = await run_instances(
            instances=args.instances,
            workspace=args.workspace,
            start_port=args.port,
            sandbox_timeout=sandbox_timeout,
            domain=domain,
            api_key=api_key,
            image=image,
            python_version=python_version,
            https=args.https,
            cert_path=cert_paths,
            key_path=key_paths,
            force_https=args.force_https,
        )

        # Print endpoints for all instances
        print("\n" + "=" * 60)
        print("VS Code Web Endpoints")
        print("=" * 60)
        for instance in instances_list:
            protocol = "https" if instance.https else "http"
            print(f"\n  Instance {instance.instance_id + 1}:")
            print(f"    Workspace: {instance.workspace}")
            print(f"    Port: {instance.port}")
            print(f"    URL: {protocol}://{instance.endpoint}/")
        print()

        # Keep sandboxes alive for the specified timeout
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
        # Clean up all instances
        print("\nCleaning up sandbox instances...")
        for instance in instances_list:
            try:
                await instance.sandbox.kill()
            except Exception as e:
                # Sandbox may have already been terminated by the server
                # (e.g., due to timeout or resource limits)
                print(
                    f"  Note: Sandbox {instance.instance_id + 1} may have already been "
                    f"terminated: {e}"
                )
        print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
