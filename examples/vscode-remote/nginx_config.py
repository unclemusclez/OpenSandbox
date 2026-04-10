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

Generates a single combined nginx config with one server block and one
location block per sandbox instance. The location path mirrors the
server-returned endpoint path, so:

  host mode:   endpoint 127.0.0.1:8443         -> location /8443/          -> proxy_pass http://127.0.0.1:8443/
  bridge mode: endpoint 127.0.0.1:55002/proxy/8443 -> location /55002/proxy/8443/ -> proxy_pass http://127.0.0.1:55002/proxy/8443/

Outside users access via https://{eip}/{location_path}

Usage:
    from nginx_config import NginxConfigGenerator

    generator = NginxConfigGenerator()
    generator.generate_config(instances=[...], server_name="1.2.3.4", cert_path=..., key_path=...)
    generator.reload_nginx()
"""

import subprocess
from pathlib import Path


LOCATION_BLOCK = """    location {url_path} {{
        proxy_pass http://127.0.0.1:{upstream_port}{upstream_path};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Proto https;
        proxy_redirect off;
        add_header Service-Worker-Allowed /;
        proxy_ssl_verify off;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering off;
        proxy_request_buffering off;
    }}
"""

SERVER_TEMPLATE = """server {{
    listen 80;
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {server_name};

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

{locations}}}
"""

CONFIG_NAME = "sandbox-vscode-remote"


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

    def generate_config(
        self,
        instances: list,
        server_name: str,
        cert_path: str,
        key_path: str,
    ) -> str:
        locations = ""
        for inst in instances:
            upstream_path = inst.upstream_path if inst.upstream_path else "/"
            locations += LOCATION_BLOCK.format(
                url_path=inst.url_path,
                upstream_port=inst.upstream_port,
                upstream_path=upstream_path,
            )

        config_content = SERVER_TEMPLATE.format(
            server_name=server_name,
            cert_path=cert_path,
            key_path=key_path,
            locations=locations,
        )

        config_path = self.sites_available_dir / CONFIG_NAME

        try:
            config_path.write_text(config_content)
            print(f"[Nginx] Config created: {config_path}")
        except IOError as e:
            raise RuntimeError(f"Failed to write nginx config: {e}") from e

        self._remove_default_site()
        self.enable_config(str(config_path))
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
        config_path = self.sites_available_dir / CONFIG_NAME

        if not config_path.exists():
            symlink_path = self.sites_enabled_dir / CONFIG_NAME
            if not symlink_path.exists() and not symlink_path.is_symlink():
                print("[Nginx] No sandbox config to clean up")
                return

        self.delete_config(str(config_path))

        try:
            self.reload_nginx()
        except RuntimeError as e:
            print(f"[Nginx] Warning: Reload after cleanup failed: {e}")
