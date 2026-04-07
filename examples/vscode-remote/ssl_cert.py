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
SSL Certificate Generator for VS Code Remote Example

Uses openssl (no pip dependencies) to generate self-signed certificates.
Each sandbox instance gets its own cert keyed by port-based URI path.

Usage:
    from ssl_cert import SSLCertificateGenerator

    gen = SSLCertificateGenerator(output_dir="/etc/nginx/ssl")
    cert, key = gen.generate_cert_for_port(port=8443)
    # -> (/etc/nginx/ssl/port-8443.crt, /etc/nginx/ssl/port-8443.key)
"""

import os
import random
import shutil
import string
import subprocess
from pathlib import Path
from typing import Optional


class SSLCertificateGenerator:
    """Generate self-signed SSL certs via openssl CLI."""

    CERT_VALIDITY_DAYS = 365
    KEY_SIZE = 2048

    def __init__(self, output_dir: str = "/etc/nginx/ssl"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_cert_for_port(
        self,
        port: int,
        server_ip: Optional[str] = None,
    ) -> tuple[str, str]:
        """Generate a self-signed cert for a specific port (used as URI path).

        Args:
            port: The code-server port number; becomes the SAN URI e.g. /8443/
            server_ip: Optional IP address to add as SAN IP (resolves SW SSL errors)

        Returns:
            Tuple of (cert_path, key_path)
        """
        name = f"port-{port}"
        cert_file = self.output_dir / f"{name}.crt"
        key_file = self.output_dir / f"{name}.key"

        if cert_file.exists() and key_file.exists():
            print(f"[SSL] Reusing existing cert: {cert_file}")
            return str(cert_file), str(key_file)

        print(f"[SSL] Generating cert for port {port}...")

        subj = f"/CN=localhost/port-{port}"

        san_parts = [f"IP:{server_ip}"] if server_ip else []
        san_parts.append(f"DNS:localhost")
        san_parts.append(f"DNS:127.0.0.1")
        san_str = ",".join(san_parts)

        conf_content = f"""[req]
default_bits = {self.KEY_SIZE}
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = localhost/port-{port}

[v3_req]
subjectAltName = {san_str}
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
"""

        conf_file = self.output_dir / f"{name}.conf"
        conf_file.write_text(conf_content)

        try:
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-nodes",
                    "-days", str(self.CERT_VALIDITY_DAYS),
                    "-newkey", f"rsa:{self.KEY_SIZE}",
                    "-keyout", str(key_file),
                    "-out", str(cert_file),
                    "-config", str(conf_file),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            os.chmod(key_file, 0o600)
            print(f"[SSL] Certificate saved: {cert_file}")
            print(f"[SSL] Key saved: {key_file}")
            return str(cert_file), str(key_file)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to generate SSL cert for port {port}: {e.stderr}"
            ) from e
        finally:
            conf_file.unlink(missing_ok=True)

    def generate_cert_for_subdomain(
        self,
        subdomain: str,
        server_ip: Optional[str] = None,
    ) -> tuple[str, str]:
        """Generate a cert for a random subdomain (nginx host-mode routing).

        Args:
            subdomain: Subdomain name e.g. 'abc12345.localhost'
            server_ip: Optional IP to add as SAN

        Returns:
            Tuple of (cert_path, key_path)
        """
        name = subdomain.replace(".", "-")
        cert_file = self.output_dir / f"{name}.crt"
        key_file = self.output_dir / f"{name}.key"

        if cert_file.exists() and key_file.exists():
            print(f"[SSL] Reusing existing cert: {cert_file}")
            return str(cert_file), str(key_file)

        print(f"[SSL] Generating cert for subdomain: {subdomain}")

        san_parts = [f"DNS:{subdomain}", f"DNS:localhost", f"DNS:127.0.0.1"]
        if server_ip:
            san_parts.insert(0, f"IP:{server_ip}")
        san_str = ",".join(san_parts)

        conf_content = f"""[req]
default_bits = {self.KEY_SIZE}
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = {subdomain}

[v3_req]
subjectAltName = {san_str}
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
"""

        conf_file = self.output_dir / f"{name}.conf"
        conf_file.write_text(conf_content)

        try:
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-nodes",
                    "-days", str(self.CERT_VALIDITY_DAYS),
                    "-newkey", f"rsa:{self.KEY_SIZE}",
                    "-keyout", str(key_file),
                    "-out", str(cert_file),
                    "-config", str(conf_file),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            os.chmod(key_file, 0o600)
            print(f"[SSL] Certificate saved: {cert_file}")
            print(f"[SSL] Key saved: {key_file}")
            return str(cert_file), str(key_file)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to generate SSL cert for {subdomain}: {e.stderr}"
            ) from e
        finally:
            conf_file.unlink(missing_ok=True)

    @staticmethod
    def generate_random_subdomain(
        length: int = 8,
        base_domain: str = "localhost",
    ) -> str:
        """Generate a random subdomain name."""
        chars = string.ascii_lowercase + string.digits
        rand = "".join(random.choice(chars) for _ in range(length))
        subdomain = f"{rand}.{base_domain}"
        print(f"[SSL] Generated subdomain: {subdomain}")
        return subdomain

    def delete_cert(self, name: str) -> None:
        """Delete cert and key by name (without extension)."""
        for ext in (".crt", ".key", ".conf"):
            p = self.output_dir / f"{name}{ext}"
            if p.exists():
                p.unlink()
                print(f"[SSL] Deleted: {p}")


def main():
    """CLI for generating certs via openssl."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate self-signed SSL certs via openssl")
    parser.add_argument("--port", type=int, help="Generate cert for a port number")
    parser.add_argument("--subdomain", type=str, help="Generate cert for a subdomain")
    parser.add_argument("--ip", type=str, help="Server IP address for SAN")
    parser.add_argument("--output-dir", type=str, default="/etc/nginx/ssl")
    args = parser.parse_args()

    gen = SSLCertificateGenerator(output_dir=args.output_dir)

    if args.port:
        cert, key = gen.generate_cert_for_port(port=args.port, server_ip=args.ip)
    elif args.subdomain:
        cert, key = gen.generate_cert_for_subdomain(subdomain=args.subdomain, server_ip=args.ip)
    else:
        parser.error("Either --port or --subdomain is required")

    print(f"\n  ssl_certificate {cert};")
    print(f"  ssl_certificate_key {key};")


if __name__ == "__main__":
    main()
