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
VS Code Remote - Multi-Instance Example

This example demonstrates how to run multiple VS Code sandbox instances
simultaneously, each with its own workspace and code-server instance.

Usage:
    uv run python examples/vscode-remote/main.py --instances 3 --workspace myproject

Features:
    - Multiple concurrent sandbox instances
    - Unique port allocation per instance
    - Workspace separation for each instance
    - Configurable timeout and image settings
"""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import timedelta
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

    # Start code-server without SSL
    # SSL termination is handled by the OpenSandbox server proxy
    # Each instance gets its own workspace directory
    start_exec = await sandbox.commands.run(
        # f"code-server --bind-addr 0.0.0.0:{port} --auth none /workspace/{workspace}",
        f"code-server --bind-addr 0.0.0.0:{port} --auth none --disable-telemetry /workspace/{workspace}",
        opts=RunCommandOpts(background=True),
    )
    await _print_logs(f"code-server-{instance_id}", start_exec)

    # Get the endpoint for this instance
    endpoint = await sandbox.get_endpoint(port)

    return SandboxInstance(
        instance_id=instance_id,
        workspace=workspace,
        port=port,
        sandbox=sandbox,
        endpoint=endpoint.endpoint,
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
) -> list[SandboxInstance]:
    """Run multiple VS Code sandbox instances concurrently."""
    config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=60),
    )

    # Create all instances concurrently
    tasks = [
        create_instance(
            instance_id=i,
            workspace=workspace,
            port=start_port + i,
            config=config,
            image=image,
            python_version=python_version,
            timeout=sandbox_timeout,
        )
        for i in range(instances)
    ]

    instances = await asyncio.gather(*tasks)
    return list(instances)


async def main() -> None:
    """Main entry point for the multi-instance VS Code example."""
    parser = argparse.ArgumentParser(
        description="Run multiple VS Code sandbox instances concurrently",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run 3 instances with default settings
  uv run python examples/vscode-remote/main.py --instances 3

  # Run 2 instances with custom workspace and port
  uv run python examples/vscode-remote/main.py --instances 2 --workspace myproject --port 8443

  # Run with custom timeout
  uv run python examples/vscode-remote/main.py --instances 2 --timeout 30
        """,
    )

    parser.add_argument(
        "--https",
        action="store_true",
        default=False,
        help="Use HTTPS URLs (requires SSL-configured OpenSandbox server)",
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

    args = parser.parse_args()

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
    print()

    try:
        # Convert timeout to timedelta
        sandbox_timeout = timedelta(minutes=args.timeout)

        # Run all instances concurrently
        instances = await run_instances(
            instances=args.instances,
            workspace=args.workspace,
            start_port=args.port,
            sandbox_timeout=sandbox_timeout,
            domain=domain,
            api_key=api_key,
            image=image,
            python_version=python_version,
        )

        # Print endpoints for all instances
        protocol = "https" if args.https else "http"
        print("\n" + "=" * 60)
        print(
            f"VS Code Web Endpoints ({protocol.upper()} - SSL termination handled by OpenSandbox Proxy):"
        )
        print("=" * 60)
        for instance in instances:
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
        for instance in instances:
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
