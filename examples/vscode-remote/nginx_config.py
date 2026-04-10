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

This module provides functionality to generate nginx reverse proxy configurations
for sandbox endpoints. It handles creation of site-available configurations,
symlink management for site-enabled, and nginx reload operations.

Usage:
    from examples.vscode_remote.nginx_config import NginxConfigGenerator

    generator = NginxConfigGenerator()
    config_path = generator.generate_config(
        server_name="abc12345.localhost",
        upstream_host="127.0.0.1",
        upstream_port=8443,
        use_https=True,
        cert_path="/etc/nginx/ssl/abc12345.localhost.crt",
        key_path="/etc/nginx/ssl/abc12345.localhost.key",
    )
    generator.enable_config(config_path)
    generator.reload_nginx()
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class NginxConfigGenerator:
    """
    Generate nginx configuration files for sandbox endpoints.

    This class handles:
    - Generating nginx configuration files
    - Creating symlinks from sites-available to sites-enabled
    - Reloading nginx to apply configuration changes
    - Testing nginx configuration validity
    """

    # Nginx configuration templates
    HTTP_TEMPLATE = """server {{
    listen 80;
    server_name {server_name};

    location {location_path} {{
        proxy_pass http://{upstream_host}:{upstream_port}{upstream_path};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""

    HTTPS_TEMPLATE = """server {{
    listen 443 ssl http2;
    server_name {server_name};

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location {location_path} {{
        proxy_pass http://{upstream_host}:{upstream_port}{upstream_path};
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
    }}
}}
"""

    def __init__(
        self,
        sites_available_dir: str = "/etc/nginx/sites-available",
        sites_enabled_dir: str = "/etc/nginx/sites-enabled",
        reload_command: str = "sudo nginx -s reload",
        test_command: str = "sudo nginx -t",
    ):
        """
        Initialize nginx configuration generator.

        Args:
            sites_available_dir: Directory for nginx site-available configurations
            sites_enabled_dir: Directory for nginx site-enabled symlinks
            reload_command: Command to reload nginx
            test_command: Command to test nginx configuration
        """
        self.sites_available_dir = Path(sites_available_dir)
        self.sites_enabled_dir = Path(sites_enabled_dir)
        self.reload_command = reload_command
        self.test_command = test_command

        # Ensure directories exist
        self.sites_available_dir.mkdir(parents=True, exist_ok=True)
        self.sites_enabled_dir.mkdir(parents=True, exist_ok=True)

    def generate_config(
        self,
        server_name: str,
        upstream_host: str,
        upstream_port: int,
        use_https: bool = False,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        location_path: Optional[str] = None,
        upstream_path: str = "",
    ) -> str:
        """
        Generate nginx configuration file.

        Args:
            server_name: Server name (domain or subdomain or IP)
            upstream_host: Host to proxy to (e.g., 127.0.0.1)
            upstream_port: Port to proxy to
            use_https: Whether to use HTTPS
            cert_path: Path to SSL certificate (required if use_https)
            key_path: Path to SSL key (required if use_https)
            location_path: URI path for location block (e.g., '/8443/' or '/abc12345/')
            upstream_path: Path component for proxy_pass (e.g., '/proxy/8443' for bridge mode)

        Returns:
            Path to generated configuration file

        Raises:
            ValueError: If HTTPS enabled but no certificates provided
            RuntimeError: If configuration file cannot be written
        """
        # Validate HTTPS parameters
        if use_https:
            if not cert_path or not key_path:
                raise ValueError(
                    "HTTPS enabled but no certificates provided. "
                    "Both cert_path and key_path are required."
                )
            if not Path(cert_path).exists():
                raise ValueError(f"Certificate file not found: {cert_path}")
            if not Path(key_path).exists():
                raise ValueError(f"Key file not found: {key_path}")

        # Select template
        template = self.HTTPS_TEMPLATE if use_https else self.HTTP_TEMPLATE

        resolved_location = location_path or "/"
        resolved_upstream_path = upstream_path if upstream_path else "/"

        config_content = template.format(
            server_name=server_name,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            cert_path=cert_path or "",
            key_path=key_path or "",
            location_path=resolved_location,
            upstream_path=resolved_upstream_path,
        )

        # Write configuration file
        config_filename = f"sandbox-{server_name.replace('.', '-')}"
        config_path = self.sites_available_dir / config_filename

        try:
            config_path.write_text(config_content)
            print(f"[Nginx] Configuration created: {config_path}")
            return str(config_path)
        except IOError as e:
            raise RuntimeError(f"Failed to write nginx configuration: {e}") from e

    def enable_config(self, config_path: str) -> None:
        """
        Enable nginx configuration by creating symlink.

        Args:
            config_path: Path to configuration file in sites-available

        Raises:
            RuntimeError: If nginx test fails or symlink cannot be created
        """
        # Test nginx configuration before enabling
        if not self.test_config():
            raise RuntimeError(
                "Nginx configuration test failed. " "Aborting enable operation."
            )

        # Create symlink
        config_filename = Path(config_path).name
        symlink_path = self.sites_enabled_dir / config_filename

        try:
            # Remove existing symlink if it exists
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()

            # Create new symlink
            symlink_path.symlink_to(config_path)
            print(f"[Nginx] Configuration enabled: {symlink_path}")
        except OSError as e:
            raise RuntimeError(f"Failed to enable nginx configuration: {e}") from e

    def disable_config(self, config_path: str) -> None:
        """
        Disable nginx configuration by removing symlink.

        Args:
            config_path: Path to configuration file in sites-available
        """
        config_filename = Path(config_path).name
        symlink_path = self.sites_enabled_dir / config_filename

        try:
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()
                print(f"[Nginx] Configuration disabled: {symlink_path}")
        except OSError as e:
            print(f"[Nginx] Warning: Failed to disable configuration: {e}")

    def delete_config(self, config_path: str) -> None:
        """
        Delete nginx configuration file.

        Args:
            config_path: Path to configuration file in sites-available
        """
        config_file = Path(config_path)

        try:
            # Disable first (remove symlink)
            self.disable_config(config_path)

            # Delete configuration file
            if config_file.exists():
                config_file.unlink()
                print(f"[Nginx] Configuration deleted: {config_file}")
        except OSError as e:
            print(f"[Nginx] Warning: Failed to delete configuration: {e}")

    def reload_nginx(self) -> None:
        """
        Reload nginx configuration.

        Raises:
            RuntimeError: If reload command fails
        """
        try:
            result = subprocess.run(
                self.reload_command,
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )
            print(f"[Nginx] Reloaded successfully")
            if result.stdout:
                print(f"[Nginx] stdout: {result.stdout}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to reload nginx: {e.stderr or e.stdout}") from e

    def test_config(self) -> bool:
        """
        Test nginx configuration validity.

        Returns:
            True if configuration is valid, False otherwise
        """
        try:
            result = subprocess.run(
                self.test_command,
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"[Nginx] Configuration test failed:")
            print(f"[Nginx] stderr: {e.stderr}")
            print(f"[Nginx] stdout: {e.stdout}")
            return False

    def cleanup_configs(self, pattern: str = "sandbox-*") -> None:
        """
        Remove all nginx configurations matching a pattern.

        Args:
            pattern: Glob pattern for configuration files (default: sandbox-*)
        """
        # Find all matching configs
        configs = list(self.sites_available_dir.glob(pattern))

        if not configs:
            print(f"[Nginx] No configurations found matching pattern: {pattern}")
            return

        print(f"[Nginx] Found {len(configs)} configuration(s) to clean up")

        # Delete each configuration
        for config_path in configs:
            self.delete_config(str(config_path))

        # Reload nginx after cleanup
        if configs:
            self.reload_nginx()


def main():
    """Main function for testing nginx configuration generator."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate nginx configuration for sandbox endpoints"
    )
    parser.add_argument(
        "--server-name",
        type=str,
        required=True,
        help="Server name (domain or subdomain)",
    )
    parser.add_argument(
        "--upstream-host",
        type=str,
        default="127.0.0.1",
        help="Host to proxy to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--upstream-port",
        type=int,
        required=True,
        help="Port to proxy to",
    )
    parser.add_argument(
        "--https",
        action="store_true",
        help="Use HTTPS configuration",
    )
    parser.add_argument(
        "--cert-path",
        type=str,
        help="Path to SSL certificate (required with --https)",
    )
    parser.add_argument(
        "--key-path",
        type=str,
        help="Path to SSL key (required with --https)",
    )
    parser.add_argument(
        "--location-path",
        type=str,
        default=None,
        help="URI path for location block (e.g., '/8443/' or '/abc12345/')",
    )
    parser.add_argument(
        "--upstream-path",
        type=str,
        default="",
        help="Path component for proxy_pass (e.g., '/proxy/8443' for bridge mode)",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable configuration after generation",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload nginx after enabling",
    )
    parser.add_argument(
        "--sites-available-dir",
        type=str,
        default="/etc/nginx/sites-available",
        help="Directory for nginx site-available configurations",
    )
    parser.add_argument(
        "--sites-enabled-dir",
        type=str,
        default="/etc/nginx/sites-enabled",
        help="Directory for nginx site-enabled symlinks",
    )

    args = parser.parse_args()

    # Create generator
    generator = NginxConfigGenerator(
        sites_available_dir=args.sites_available_dir,
        sites_enabled_dir=args.sites_enabled_dir,
    )

    # Generate configuration
    config_path = generator.generate_config(
        server_name=args.server_name,
        upstream_host=args.upstream_host,
        upstream_port=args.upstream_port,
        use_https=args.https,
        cert_path=args.cert_path,
        key_path=args.key_path,
        location_path=args.location_path,
        upstream_path=args.upstream_path,
    )

    # Enable configuration if requested
    if args.enable:
        generator.enable_config(config_path)

        # Reload nginx if requested
        if args.reload:
            generator.reload_nginx()

    print(f"\nConfiguration file: {config_path}")
    print(f"To enable manually: sudo ln -s {config_path} {args.sites_enabled_dir}/")
    print(f"To reload nginx: sudo nginx -s reload")


if __name__ == "__main__":
    main()
