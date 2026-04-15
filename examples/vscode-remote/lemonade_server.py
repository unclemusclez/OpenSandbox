#!/usr/bin/env python3
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
Lemonade Server Manager for VS Code Remote Example

Installs, configures, and manages a local Lemonade inference server
that provides LLM endpoints for VS Code extensions in sandbox instances.

The server runs on the host machine and exposes an OpenAI-compatible API
that VS Code extensions (Continue, Cline, etc.) inside sandbox containers
can connect to. Bridge/host networking is handled by the separate main.py
orchestrator; this script only manages the Lemonade server lifecycle.

Usage:
    # One-time installation
    python lemonade_server.py install

    # Configure server settings
    python lemonade_server.py configure --host 0.0.0.0 --port 13305 --generate-keys

    # Start the server
    python lemonade_server.py start

    # Pull a model
    python lemonade_server.py pull --model Gemma-3-4b-it-GGUF

    # Full setup (install + configure + start + pull model)
    python lemonade_server.py run --model Gemma-3-4b-it-GGUF --external-ip 1.2.3.4

    # Check server status
    python lemonade_server.py status

    # Stop the server
    python lemonade_server.py stop

    # Cleanup
    python lemonade_server.py cleanup
"""

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

LEMONADE_CONFIG_DIR = Path("/var/lib/lemonade/.cache/lemonade")
LEMONADE_CONFIG_PATH = LEMONADE_CONFIG_DIR / "config.json"
SYSTEMD_SERVICE_NAME = "lemonade-server"
SYSTEMD_OVERRIDE_DIR = Path(
    f"/etc/systemd/system/{SYSTEMD_SERVICE_NAME}.service.d"
)
DEFAULT_MODEL = "Gemma-3-4b-it-GGUF"
DEFAULT_PORT = 13305
DEFAULT_HOST = "0.0.0.0"

LLAMACPP_DEFAULTS: dict = {
    "backend": "auto",
    "args": "",
    "prefer_system": False,
    "rocm_bin": "builtin",
    "vulkan_bin": "builtin",
    "cpu_bin": "builtin",
}
WHISPERCPP_DEFAULTS: dict = {
    "backend": "auto",
    "args": "",
    "cpu_bin": "builtin",
    "npu_bin": "builtin",
}
SDCPP_DEFAULTS: dict = {
    "backend": "auto",
    "args": "",
    "steps": 20,
    "cfg_scale": 7.0,
    "width": 512,
    "height": 512,
    "cpu_bin": "builtin",
    "rocm_bin": "builtin",
    "vulkan_bin": "builtin",
}


def generate_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)


def _needs_sudo() -> bool:
    try:
        return os.geteuid() != 0
    except AttributeError:
        return False


def _run_cmd(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    sudo: bool = False,
) -> subprocess.CompletedProcess[str]:
    if sudo and _needs_sudo():
        cmd = ["sudo", *cmd]
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        check=check,
    )


def _sudo_write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    except PermissionError:
        tmp_path = Path(f"/tmp/{path.name}")
        tmp_path.write_text(content)
        _run_cmd(["cp", str(tmp_path), str(path)], sudo=True)
        tmp_path.unlink(missing_ok=True)


def _sudo_read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        try:
            result = _run_cmd(["cat", str(path)], sudo=True)
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return None


def detect_docker_host_ip() -> Optional[str]:
    """Detect the host IP reachable from Docker containers via the bridge network."""
    try:
        result = _run_cmd(
            ["docker", "network", "inspect", "bridge"],
            check=False,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data:
                gateway = (
                    data[0]
                    .get("IPAM", {})
                    .get("Config", [{}])[0]
                    .get("Gateway")
                )
                if gateway:
                    return gateway
    except Exception:
        pass
    return None


class LemonadeServerManager:
    """Manages installation, configuration, and lifecycle of the Lemonade inference server."""

    def __init__(
        self,
        config_dir: Path = LEMONADE_CONFIG_DIR,
        api_key: Optional[str] = None,
        admin_api_key: Optional[str] = None,
    ):
        self.config_dir = config_dir
        self.config_path = config_dir / "config.json"
        self._api_key = api_key
        self._admin_api_key = admin_api_key

    @property
    def api_key(self) -> str:
        if self._api_key:
            return self._api_key
        return os.getenv("LEMONADE_API_KEY", "")

    @property
    def admin_api_key(self) -> str:
        if self._admin_api_key:
            return self._admin_api_key
        return os.getenv("LEMONADE_ADMIN_API_KEY", "")

    def is_installed(self) -> bool:
        for cmd in ("lemonade-server", "lemonade"):
            result = _run_cmd(["which", cmd], check=False)
            if result.returncode == 0:
                return True
        return False

    def install(self) -> None:
        """Install lemonade-server via PPA and update PCI IDs for GPU detection."""
        if self.is_installed():
            print("[Lemonade] Already installed")
            return

        print("[Lemonade] Installing lemonade-server via PPA...")
        _run_cmd(
            ["add-apt-repository", "-y", "ppa:lemonade-team/stable"], sudo=True
        )
        _run_cmd(["apt-get", "update"], sudo=True)
        _run_cmd(["apt-get", "install", "-y", "lemonade-server"], sudo=True)
        _run_cmd(["update-pciids"], sudo=True, check=False)
        print("[Lemonade] Installation complete")

    def configure(
        self,
        port: int = DEFAULT_PORT,
        host: str = DEFAULT_HOST,
        llamacpp_backend: str = "rocm",
        ctx_size: int = 4096,
        max_loaded_models: int = 1,
        generate_keys: bool = False,
    ) -> None:
        """Write config.json and optionally set API keys in systemd override."""
        existing = _sudo_read_json(self.config_path) or {}

        config: dict = {
            "config_version": existing.get("config_version", 1),
            "port": port,
            "host": host,
            "log_level": existing.get("log_level", "info"),
            "global_timeout": existing.get("global_timeout", 300),
            "max_loaded_models": max_loaded_models,
            "no_broadcast": existing.get("no_broadcast", False),
            "extra_models_dir": existing.get("extra_models_dir", ""),
            "models_dir": existing.get("models_dir", "auto"),
            "ctx_size": ctx_size,
            "offline": existing.get("offline", False),
            "disable_model_filtering": existing.get(
                "disable_model_filtering", False
            ),
            "enable_dgpu_gtt": existing.get("enable_dgpu_gtt", False),
            "llamacpp": {
                **LLAMACPP_DEFAULTS,
                **existing.get("llamacpp", {}),
                "backend": llamacpp_backend,
            },
            "whispercpp": {
                **WHISPERCPP_DEFAULTS,
                **existing.get("whispercpp", {}),
            },
            "sdcpp": {
                **SDCPP_DEFAULTS,
                **existing.get("sdcpp", {}),
            },
            "flm": {**{"args": ""}, **existing.get("flm", {})},
            "ryzenai": {
                **{"server_bin": "builtin"},
                **existing.get("ryzenai", {}),
            },
            "kokoro": {**{"cpu_bin": "builtin"}, **existing.get("kokoro", {})},
        }

        _sudo_write_json(self.config_path, config)
        print(f"[Lemonade] Configuration written to {self.config_path}")

        if generate_keys:
            self._configure_api_keys()

    def _configure_api_keys(self) -> tuple[str, str]:
        """Generate API keys and persist them in a systemd override file."""
        api_key = self.api_key or generate_password()
        admin_api_key = self.admin_api_key or generate_password()

        try:
            SYSTEMD_OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            _run_cmd(["mkdir", "-p", str(SYSTEMD_OVERRIDE_DIR)], sudo=True)

        override_path = SYSTEMD_OVERRIDE_DIR / "override.conf"
        content = (
            "[Service]\n"
            f'Environment="LEMONADE_API_KEY={api_key}"\n'
            f'Environment="LEMONADE_ADMIN_API_KEY={admin_api_key}"\n'
        )
        try:
            override_path.write_text(content)
        except PermissionError:
            tmp_path = Path(f"/tmp/{SYSTEMD_SERVICE_NAME}-override.conf")
            tmp_path.write_text(content)
            _run_cmd(["cp", str(tmp_path), str(override_path)], sudo=True)
            tmp_path.unlink(missing_ok=True)

        _run_cmd(["systemctl", "daemon-reload"], sudo=True)

        self._api_key = api_key
        self._admin_api_key = admin_api_key

        print("[Lemonade] API keys configured in systemd override")
        print(f"[Lemonade]   API Key:       {api_key}")
        print(f"[Lemonade]   Admin API Key: {admin_api_key}")
        return api_key, admin_api_key

    def start(self) -> None:
        _run_cmd(["systemctl", "start", SYSTEMD_SERVICE_NAME], sudo=True)
        print("[Lemonade] Server started")

    def stop(self) -> None:
        _run_cmd(["systemctl", "stop", SYSTEMD_SERVICE_NAME], sudo=True)
        print("[Lemonade] Server stopped")

    def restart(self) -> None:
        _run_cmd(["systemctl", "restart", SYSTEMD_SERVICE_NAME], sudo=True)
        print("[Lemonade] Server restarted")

    def status(self) -> bool:
        result = _run_cmd(
            ["systemctl", "is-active", SYSTEMD_SERVICE_NAME],
            check=False,
        )
        active = result.stdout.strip() == "active"
        if active:
            print("[Lemonade] Server is running")
        else:
            print(f"[Lemonade] Server status: {result.stdout.strip()}")
        return active

    def pull_model(self, model: str) -> None:
        """Download a model to the local cache via the lemonade CLI."""
        print(f"[Lemonade] Pulling model: {model}")
        _run_cmd(
            ["lemonade", "pull", model],
            check=True,
            capture=False,
            sudo=False,
        )
        print(f"[Lemonade] Model pulled: {model}")

    def load_model(self, model: str, timeout: int = 120) -> bool:
        """Load a model via the Lemonade HTTP API so it is ready for inference."""
        endpoint = self.get_endpoint()
        url = f"{endpoint}/api/v1/load"
        payload = json.dumps({"model": model}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        auth_key = self.admin_api_key or self.api_key
        if auth_key:
            req.add_header("Authorization", f"Bearer {auth_key}")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    print(f"[Lemonade] Model loaded: {model}")
                    return True
                print(f"[Lemonade] Load failed with status {resp.status}")
                return False
        except urllib.error.URLError as e:
            print(f"[Lemonade] Model load error: {e}")
            return False

    def get_endpoint(self) -> str:
        config = _sudo_read_json(self.config_path)
        if config:
            host = config.get("host", DEFAULT_HOST)
            port = config.get("port", DEFAULT_PORT)
            if host == "0.0.0.0":
                host = "localhost"
            return f"http://{host}:{port}"
        return f"http://localhost:{DEFAULT_PORT}"

    def get_port(self) -> int:
        config = _sudo_read_json(self.config_path)
        if config:
            return config.get("port", DEFAULT_PORT)
        return DEFAULT_PORT

    def generate_kilo_config(
        self,
        model: str = DEFAULT_MODEL,
        external_ip: Optional[str] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Generate a kilo.json config for Kilo Code pointing at this Lemonade server.

        The base URL is resolved to the best reachable address from inside
        sandbox containers: external_ip > Docker bridge gateway > localhost.

        Args:
            model: Model ID to configure in Kilo Code.
            external_ip: External IP for sandbox access.
            output_path: Path to write kilo.json. Defaults to ./kilo.json.

        Returns:
            Path to the generated kilo.json file.
        """
        port = self.get_port()
        docker_ip = detect_docker_host_ip()

        if external_ip:
            base_host = external_ip
        elif docker_ip:
            base_host = docker_ip
        else:
            base_host = "localhost"

        base_url = f"http://{base_host}:{port}/v1"
        auth_key = self.admin_api_key or self.api_key or "none"

        model_id = model.lower().replace("-", "-").replace(".", "-")
        config: dict = {
            "provider": {
                "lemonade": {
                    "models": {
                        model_id: {
                            "name": model,
                            "limit": {
                                "context": self._get_ctx_size(),
                                "output": 4096,
                            },
                        },
                    },
                    "options": {
                        "apiKey": auth_key,
                        "baseURL": base_url,
                    },
                },
            },
            "model": f"lemonade/{model_id}",
        }

        target = output_path or Path("kilo.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(config, indent=2))

        print(f"[Lemonade] Kilo Code config written to {target}")
        print(f"[Lemonade]   Provider:  lemonade")
        print(f"[Lemonade]   Base URL:  {base_url}")
        print(f"[Lemonade]   Model:     lemonade/{model_id}")
        if auth_key != "none":
            print(f"[Lemonade]   API Key:   {auth_key}")
        return target

    def _get_ctx_size(self) -> int:
        config = _sudo_read_json(self.config_path)
        if config:
            return config.get("ctx_size", 4096)
        return 4096

    def cleanup(self) -> None:
        self.stop()
        print("[Lemonade] Cleanup complete")


def _print_endpoint_info(
    manager: LemonadeServerManager,
    model: str,
    port: int,
    external_ip: Optional[str] = None,
) -> None:
    endpoint = manager.get_endpoint()
    docker_ip = detect_docker_host_ip()
    auth_key = manager.admin_api_key or manager.api_key

    print("\n" + "=" * 70)
    print("Lemonade Inference Server")
    print("=" * 70)
    print(f"  Local endpoint: {endpoint}")
    print(f"  OpenAI API:     {endpoint}/v1/")
    if external_ip:
        print(f"  External API:   http://{external_ip}:{port}/v1/")
    print(f"  Model:          {model}")
    if manager.api_key:
        print(f"  API Key:        {manager.api_key}")
    if manager.admin_api_key:
        print(f"  Admin API Key:  {manager.admin_api_key}")

    print()
    print("VS Code Extension Configuration (for sandbox instances):")
    if docker_ip:
        print(f"  Base URL:  http://{docker_ip}:{port}/v1")
    if external_ip:
        print(f"  Base URL:  http://{external_ip}:{port}/v1")
    elif not docker_ip:
        print(f"  Base URL:  http://localhost:{port}/v1")
    print(f"  API Key:   {auth_key or '(none)'}")
    print(f"  Model:     {model}")
    print()


async def cmd_run(
    model: str = DEFAULT_MODEL,
    port: int = DEFAULT_PORT,
    host: str = DEFAULT_HOST,
    llamacpp_backend: str = "rocm",
    ctx_size: int = 4096,
    max_loaded_models: int = 1,
    generate_keys: bool = False,
    skip_install: bool = False,
    external_ip: Optional[str] = None,
    api_key: Optional[str] = None,
    admin_api_key: Optional[str] = None,
    kilo_config: Optional[str] = None,
) -> None:
    manager = LemonadeServerManager(
        api_key=api_key,
        admin_api_key=admin_api_key,
    )

    if not skip_install and not manager.is_installed():
        manager.install()

    manager.configure(
        port=port,
        host=host,
        llamacpp_backend=llamacpp_backend,
        ctx_size=ctx_size,
        max_loaded_models=max_loaded_models,
        generate_keys=generate_keys,
    )

    manager.restart()

    print("[Lemonade] Waiting for server to be ready...")
    await asyncio.sleep(3)

    if not manager.status():
        print("[Lemonade] Error: Server failed to start")
        sys.exit(1)

    manager.pull_model(model)

    await asyncio.sleep(2)
    manager.load_model(model)

    _print_endpoint_info(manager, model, port, external_ip)

    if generate_keys or kilo_config:
        output = Path(kilo_config) if kilo_config else Path("kilo.json")
        manager.generate_kilo_config(
            model=model,
            external_ip=external_ip,
            output_path=output,
        )

    print("Keeping server alive. Press Ctrl+C to exit.")

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n[Lemonade] Stopping...")
    finally:
        manager.stop()
        print("[Lemonade] Stopped")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Lemonade inference server for VS Code Remote",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # One-time installation
  python lemonade_server.py install

  # Configure with API keys
  python lemonade_server.py configure --generate-keys --host 0.0.0.0

  # Start the server
  python lemonade_server.py start

  # Pull a model
  python lemonade_server.py pull --model Gemma-3-4b-it-GGUF

  # Full setup (install + configure + start + pull model)
  python lemonade_server.py run --model Gemma-3-4b-it-GGUF --generate-keys --external-ip 1.2.3.4

  # Check server status
  python lemonade_server.py status

  # Stop the server
  python lemonade_server.py stop

  # Cleanup
  python lemonade_server.py cleanup
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("install", help="Install lemonade-server via PPA")

    config_parser = subparsers.add_parser(
        "configure", help="Configure server settings"
    )
    config_parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})"
    )
    config_parser.add_argument(
        "--host", type=str, default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})"
    )
    config_parser.add_argument(
        "--llamacpp-backend",
        type=str,
        default="rocm",
        help="llama.cpp backend: auto, rocm, vulkan, cpu (default: rocm)",
    )
    config_parser.add_argument(
        "--ctx-size", type=int, default=4096, help="Default context size (default: 4096)"
    )
    config_parser.add_argument(
        "--max-loaded-models",
        type=int,
        default=1,
        help="Max models per type slot (default: 1)",
    )
    config_parser.add_argument(
        "--generate-keys",
        action="store_true",
        default=False,
        help="Generate API key and admin API key, store in systemd override",
    )
    config_parser.add_argument(
        "--api-key", type=str, default=None, help="Set a specific API key (overrides generate)"
    )
    config_parser.add_argument(
        "--admin-api-key",
        type=str,
        default=None,
        help="Set a specific admin API key (overrides generate)",
    )
    config_parser.add_argument(
        "--kilo-config",
        type=str,
        default=None,
        help="Generate kilo.json for Kilo Code at this path (requires --generate-keys or --api-key)",
    )
    config_parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Model ID for kilo.json (default: {DEFAULT_MODEL})",
    )
    config_parser.add_argument(
        "--external-ip",
        type=str,
        default=None,
        help="External IP for kilo.json base URL (auto-detect Docker gateway if omitted)",
    )

    subparsers.add_parser("start", help="Start the server")
    subparsers.add_parser("stop", help="Stop the server")
    subparsers.add_parser("restart", help="Restart the server")
    subparsers.add_parser("status", help="Check server status")

    pull_parser = subparsers.add_parser("pull", help="Pull a model to local cache")
    pull_parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Model to pull (default: {DEFAULT_MODEL})",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Full setup: install + configure + start + pull model + keep alive",
    )
    run_parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Model to pull and load (default: {DEFAULT_MODEL})",
    )
    run_parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})"
    )
    run_parser.add_argument(
        "--host", type=str, default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})"
    )
    run_parser.add_argument(
        "--llamacpp-backend",
        type=str,
        default="rocm",
        help="llama.cpp backend: auto, rocm, vulkan, cpu (default: rocm)",
    )
    run_parser.add_argument(
        "--ctx-size", type=int, default=4096, help="Default context size (default: 4096)"
    )
    run_parser.add_argument(
        "--max-loaded-models",
        type=int,
        default=1,
        help="Max models per type slot (default: 1)",
    )
    run_parser.add_argument(
        "--generate-keys",
        action="store_true",
        default=False,
        help="Generate API key and admin API key",
    )
    run_parser.add_argument(
        "--api-key", type=str, default=None, help="Set a specific API key"
    )
    run_parser.add_argument(
        "--admin-api-key",
        type=str,
        default=None,
        help="Set a specific admin API key",
    )
    run_parser.add_argument(
        "--skip-install",
        action="store_true",
        default=False,
        help="Skip installation check (server already installed)",
    )
    run_parser.add_argument(
        "--external-ip",
        type=str,
        default=None,
        help="External IP for sandbox access URLs (auto-detect Docker gateway if omitted)",
    )
    run_parser.add_argument(
        "--kilo-config",
        type=str,
        default=None,
        help="Generate kilo.json for Kilo Code at this path (default: ./kilo.json when --generate-keys is set)",
    )

    subparsers.add_parser("cleanup", help="Stop server and clean up")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    manager = LemonadeServerManager(
        api_key=getattr(args, "api_key", None),
        admin_api_key=getattr(args, "admin_api_key", None),
    )

    if args.command == "install":
        manager.install()
    elif args.command == "configure":
        manager.configure(
            port=args.port,
            host=args.host,
            llamacpp_backend=args.llamacpp_backend,
            ctx_size=args.ctx_size,
            max_loaded_models=args.max_loaded_models,
            generate_keys=args.generate_keys,
        )
        if args.kilo_config and (manager.api_key or manager.admin_api_key):
            manager.generate_kilo_config(
                model=args.model,
                external_ip=args.external_ip,
                output_path=Path(args.kilo_config) if args.kilo_config else None,
            )
        elif args.kilo_config:
            print("[Lemonade] Warning: --kilo-config requires --generate-keys or --api-key to set authentication")
    elif args.command == "start":
        manager.start()
    elif args.command == "stop":
        manager.stop()
    elif args.command == "restart":
        manager.restart()
    elif args.command == "status":
        manager.status()
    elif args.command == "pull":
        manager.pull_model(args.model)
    elif args.command == "run":
        asyncio.run(
            cmd_run(
                model=args.model,
                port=args.port,
                host=args.host,
                llamacpp_backend=args.llamacpp_backend,
                ctx_size=args.ctx_size,
                max_loaded_models=args.max_loaded_models,
                generate_keys=args.generate_keys,
                skip_install=args.skip_install,
                external_ip=args.external_ip,
                api_key=args.api_key,
                admin_api_key=args.admin_api_key,
                kilo_config=args.kilo_config,
            )
        )
    elif args.command == "cleanup":
        manager.cleanup()


if __name__ == "__main__":
    main()
