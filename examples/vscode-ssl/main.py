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
VS Code SSL Example

Single-instance VS Code sandbox with built-in code-server SSL support.
Generates a self-signed certificate inside the sandbox using openssl,
then starts code-server with --cert and --cert-key flags for native HTTPS.

No nginx or external reverse proxy required.

Usage:
    # Default (self-signed cert, HTTPS on port 8443)
    python examples/vscode-ssl/main.py

    # Custom code-server port
    python examples/vscode-ssl/main.py --port 9443

    # With password authentication
    python examples/vscode-ssl/main.py --secure

    # Auto-detect external IP for cert SAN
    python examples/vscode-ssl/main.py --external-ip 1.2.3.4
"""

import argparse
import asyncio
import os
import secrets
from datetime import timedelta
from typing import Optional

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts


def generate_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)


def detect_external_ip() -> Optional[str]:
    """Detect the external IP from hostname -I, filtering private ranges."""
    import subprocess

    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            check=True,
        )
        ips = result.stdout.strip().split()
        for ip in ips:
            if ip.startswith(("10.", "172.", "127.", "192.168.")):
                continue
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                return ip
    except Exception:
        pass
    return None


async def _print_logs(label: str, execution) -> None:
    for msg in execution.logs.stdout:
        print(f"[{label} stdout] {msg.text}")
    for msg in execution.logs.stderr:
        print(f"[{label} stderr] {msg.text}")
    if execution.error:
        print(f"[{label} error] {execution.error.name}: {execution.error.value}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run VS Code sandbox with native code-server SSL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default (self-signed cert, HTTPS on port 8443)
  python main.py

  # With password authentication
  python main.py --secure

  # Auto-detect external IP for cert SAN
  python main.py --external-ip 1.2.3.4

  # Custom code-server port
  python main.py --port 9443
        """,
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help="Port for code-server HTTPS (default: 8443)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Timeout in minutes to keep sandbox alive (default: 10)",
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
        help="Docker image for sandbox (default: opensandbox/vscode-ssl:latest)",
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
        help="Enable password authentication for code-server",
    )
    parser.add_argument(
        "--external-ip",
        type=str,
        default=None,
        help="External IP for certificate SAN (auto-detected from hostname -I if omitted)",
    )
    parser.add_argument(
        "--cert-dir",
        type=str,
        default="/certs",
        help="Directory inside sandbox for SSL certificates (default: /certs)",
    )

    args = parser.parse_args()

    external_ip = args.external_ip
    if not external_ip:
        external_ip = detect_external_ip()
        if external_ip:
            print(f"[Auto] Detected external IP: {external_ip}")

    domain = args.domain or os.getenv("SANDBOX_DOMAIN", "localhost:8080")
    api_key = args.api_key or os.getenv("SANDBOX_API_KEY")
    image = args.image or os.getenv("SANDBOX_IMAGE", "opensandbox/vscode-ssl:latest")
    python_version = args.python_version or os.getenv("PYTHON_VERSION", "3.11")

    print("Starting VS Code sandbox with SSL...")
    print(f"  Domain: {domain}")
    print(f"  Image: {image}")
    print(f"  Port: {args.port}")
    print(f"  Secure: {'Yes (password)' if args.secure else 'No (--auth none)'}")
    if external_ip:
        print(f"  External IP: {external_ip}")
    print()

    config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=60),
    )

    env = {"PYTHON_VERSION": python_version}
    sandbox = await Sandbox.create(
        image,
        connection_config=config,
        env=env,
        timeout=timedelta(minutes=args.timeout),
    )

    try:
        cert_dir = args.cert_dir
        cert_path = f"{cert_dir}/server.crt"
        key_path = f"{cert_dir}/server.key"

        check_exec = await sandbox.commands.run("which openssl")
        if check_exec.exit_code != 0:
            print("[SSL] Installing openssl...")
            install_exec = await sandbox.commands.run(
                "apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*"
            )
            if install_exec.exit_code != 0:
                raise RuntimeError("Failed to install openssl inside sandbox")

        print("[SSL] Generating self-signed certificate inside sandbox...")

        await sandbox.commands.run(f"mkdir -p {cert_dir}")

        san_entries = ["DNS:localhost", "IP:127.0.0.1"]
        if external_ip:
            san_entries.append(f"IP:{external_ip}")
        san_string = ",".join(san_entries)

        openssl_cmd = (
            f"openssl req -x509 -newkey rsa:2048 "
            f"-keyout {key_path} "
            f"-out {cert_path} "
            f"-days 365 -nodes "
            f'-subj "/CN=code-server" '
            f'-addext "subjectAltName={san_string}"'
        )
        cert_exec = await sandbox.commands.run(openssl_cmd)
        await _print_logs("SSL", cert_exec)
        if cert_exec.exit_code != 0:
            raise RuntimeError(
                f"Certificate generation failed with exit code {cert_exec.exit_code}"
            )

        print(f"[SSL] Certificate generated at {cert_path}")

        auth_flag = "--auth none"
        password: Optional[str] = None
        if args.secure:
            password = generate_password()
            auth_flag = "--auth password"

        code_server_cmd = (
            f"code-server --bind-addr 0.0.0.0:{args.port} "
            f"{auth_flag} "
            f"--disable-telemetry "
            f"--cert {cert_path} "
            f"--cert-key {key_path} "
            f"/workspace"
        )
        print(f"[code-server] Starting with SSL on port {args.port}")

        start_exec = await sandbox.commands.run(
            code_server_cmd,
            opts=RunCommandOpts(background=True),
        )
        await _print_logs("code-server", start_exec)

        endpoint = await sandbox.get_endpoint(args.port)
        endpoint_str = endpoint.endpoint

        endpoint_port_part = endpoint_str.split("/", 1)[0]
        if ":" in endpoint_port_part:
            connect_port = endpoint_port_part.rsplit(":", 1)[1]
        else:
            connect_port = "443"

        if "/" in endpoint_str:
            https_url = f"https://{external_ip or 'localhost'}/{endpoint_str.split(':', 1)[1] if ':' in endpoint_str else endpoint_str}/"
        else:
            https_url = f"https://{endpoint_str}/"

        print("\n" + "=" * 50)
        print("VS Code Web Endpoint (HTTPS)")
        print("=" * 50)
        print(f"  URL: {https_url}")
        print(f"  Direct: https://{endpoint_str}/")
        if password:
            print(f"  Password: {password}")
        print()

        if external_ip:
            print(
                "  Note: Self-signed cert includes your external IP in SAN.\n"
                "  Browsers will show a security warning — accept it to proceed.\n"
                "  For CA-trusted certs, consider using mkcert on the host instead."
            )
        else:
            print(
                "  Note: Self-signed cert covers localhost/127.0.0.1 only.\n"
                "  Use --external-ip to add your IP to the certificate SAN."
            )

        print(
            f"\nKeeping sandbox alive for {args.timeout} minutes. "
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
        try:
            await sandbox.kill()
        except Exception as e:
            print(f"  Note: Sandbox may already be terminated: {e}")
        print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
