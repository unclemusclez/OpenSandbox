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
Nginx Configuration Generator for VS Code Remote Example

Generates per-port nginx configs in /etc/nginx/sites-available/, symlinks them
into /etc/nginx/sites-enabled/. Each port gets its own config file:

  sandbox-vscode-remote-{port}

Location is always /{port}/, proxying to the full upstream endpoint.
Bridge/host mode is auto-detected from the endpoint format.

  host mode:   endpoint 127.0.0.1:8443             -> location /8443/ -> proxy_pass http://127.0.0.1:8443/
  bridge mode: endpoint 127.0.0.1:55002/proxy/8443  -> location /8443/ -> proxy_pass http://127.0.0.1:55002/proxy/8443/

Usage:
    from nginx_config import NginxConfigGenerator

    generator = NginxConfigGenerator()
    path = generator.generate_port_config(
        port=8443,
        server_name="_",
        upstream_port=55002,
        upstream_path="/proxy/8443",
        cert_path="/etc/nginx/ssl/vscode-remote.crt",
        key_path="/etc/nginx/ssl/vscode-remote.key",
    )
    generator.enable_config(path)
    generator.reload_nginx()
"""

import subprocess
from pathlib import Path


PORT_CONFIG_TEMPLATE = """server {{
    listen 80;
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {server_name};

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location /{port}/ {{
        proxy_pass http://127.0.0.1:{upstream_port}{upstream_path};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_redirect off;
        proxy_cookie_path / /{port}/;
        add_header Service-Worker-Allowed /;
        proxy_ssl_verify off;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering off;
        proxy_request_buffering off;
    }}
}}
"""

CONFIG_PREFIX = "sandbox-vscode-remote-"


class NginxConfigGenerator:

    def __init__(
        self,
        sites_available_dir: str = "/etc/nginx/sites-available",
        sites_enabled_dir: str = "/etc/nginx/sites-enabled",
        reload_command: str = "sudo nginx -s reload",
        test_command: str = "sudo nginx -t",
    ):
        self.sites_available_dir = Path(sites_available_dir)
        self.sites_enabled_dir = Path(sites_enabled_dir)
        self.reload_command = reload_command
        self.test_command = test_command

        self.sites_available_dir.mkdir(parents=True, exist_ok=True)
        self.sites_enabled_dir.mkdir(parents=True, exist_ok=True)

    def _remove_default_site(self) -> None:
        default_symlink = self.sites_enabled_dir / "default"
        if default_symlink.exists() or default_symlink.is_symlink():
            try:
                default_symlink.unlink()
                print("[Nginx] Removed default site to avoid conflict")
            except OSError as e:
                print(f"[Nginx] Warning: Could not remove default site: {e}")

    def generate_port_config(
        self,
        port: int,
        server_name: str,
        upstream_port: int,
        upstream_path: str,
        cert_path: str,
        key_path: str,
    ) -> str:
        config_content = PORT_CONFIG_TEMPLATE.format(
            port=port,
            server_name=server_name,
            upstream_port=upstream_port,
            upstream_path=upstream_path,
            cert_path=cert_path,
            key_path=key_path,
        )

        config_filename = f"{CONFIG_PREFIX}{port}"
        config_path = self.sites_available_dir / config_filename

        try:
            config_path.write_text(config_content)
            print(f"[Nginx] Config created: {config_path}")
        except IOError as e:
            raise RuntimeError(f"Failed to write nginx config: {e}") from e

        return str(config_path)

    def enable_config(self, config_path: str) -> None:
        config_filename = Path(config_path).name
        symlink_path = self.sites_enabled_dir / config_filename

        try:
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()

            symlink_path.symlink_to(config_path)
            print(f"[Nginx] Config enabled: {symlink_path}")
        except OSError as e:
            raise RuntimeError(f"Failed to enable nginx config: {e}") from e

    def disable_config(self, config_path: str) -> None:
        config_filename = Path(config_path).name
        symlink_path = self.sites_enabled_dir / config_filename

        try:
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()
                print(f"[Nginx] Config disabled: {symlink_path}")
        except OSError as e:
            print(f"[Nginx] Warning: Failed to disable config: {e}")

    def delete_config(self, config_path: str) -> None:
        config_file = Path(config_path)

        try:
            self.disable_config(config_path)

            if config_file.exists():
                config_file.unlink()
                print(f"[Nginx] Config deleted: {config_file}")
        except OSError as e:
            print(f"[Nginx] Warning: Failed to delete config: {e}")

    def delete_config_by_port(self, port: int) -> None:
        config_filename = f"{CONFIG_PREFIX}{port}"
        config_path = self.sites_available_dir / config_filename
        if config_path.exists():
            self.delete_config(str(config_path))

    def reload_nginx(self) -> None:
        try:
            subprocess.run(
                self.reload_command,
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )
            print("[Nginx] Reloaded successfully")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to reload nginx: {e.stderr or e.stdout}"
            ) from e

    def test_config(self) -> bool:
        try:
            subprocess.run(
                self.test_command,
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            print("[Nginx] Config test failed:")
            print(f"[Nginx] stderr: {e.stderr}")
            print(f"[Nginx] stdout: {e.stdout}")
            return False

    def cleanup_all(self) -> None:
        configs = list(self.sites_available_dir.glob(f"{CONFIG_PREFIX}*"))

        if not configs:
            print("[Nginx] No sandbox configs to clean up")
            return

        print(f"[Nginx] Found {len(configs)} sandbox config(s) to clean up")

        for config_path in configs:
            self.delete_config(str(config_path))

        try:
            self.reload_nginx()
        except RuntimeError as e:
            print(f"[Nginx] Warning: Reload after cleanup failed: {e}")
