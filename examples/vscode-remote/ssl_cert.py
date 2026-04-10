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

Uses mkcert (preferred) to generate CA-trusted certificates that browsers
accept without warnings. Falls back to openssl if mkcert is not installed.

mkcert certs fix Service Worker SSL errors because the browser trusts
the local CA that mkcert installs.

Usage:
    from ssl_cert import SSLCertificateGenerator

    gen = SSLCertificateGenerator(output_dir="/etc/nginx/ssl")
    cert, key = gen.generate_server_cert(server_ip="165.245.138.159")
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class SSLCertificateGenerator:

    def __init__(self, output_dir: str = "/etc/nginx/ssl"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._mkcert_path: Optional[str] = None

    def _find_mkcert(self) -> Optional[str]:
        if self._mkcert_path is not None:
            return self._mkcert_path

        mkcert = shutil.which("mkcert")
        if mkcert:
            self._mkcert_path = mkcert
            return mkcert

        return None

    def _check_mkcert_ca(self) -> bool:
        mkcert = self._find_mkcert()
        if not mkcert:
            return False
        try:
            result = subprocess.run(
                [mkcert, "-caroot"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _install_mkcert_ca(self) -> bool:
        mkcert = self._find_mkcert()
        if not mkcert:
            return False
        try:
            subprocess.run(
                [mkcert, "-install"],
                check=True,
                capture_output=True,
            )
            print("[SSL] mkcert CA installed")
            return True
        except subprocess.CalledProcessError as e:
            print(f"[SSL] Warning: Failed to install mkcert CA: {e}")
            return False

    def generate_server_cert(
        self,
        server_ip: Optional[str] = None,
    ) -> tuple[str, str]:
        """Generate a single shared cert for the whole instance.

        Uses mkcert if available (CA-trusted, no browser warnings).
        Falls back to openssl self-signed.

        Args:
            server_ip: External IP for SAN (fixes Service Worker SSL errors)

        Returns:
            Tuple of (cert_path, key_path)
        """
        cert_file = self.output_dir / "vscode-remote.pem"
        key_file = self.output_dir / "vscode-remote-key.pem"

        if cert_file.exists() and key_file.exists():
            print(f"[SSL] Reusing existing cert: {cert_file}")
            return str(cert_file), str(key_file)

        mkcert = self._find_mkcert()
        if mkcert:
            if not self._check_mkcert_ca():
                if not self._install_mkcert_ca():
                    print("[SSL] mkcert CA not available, falling back to openssl")
                    return self._generate_openssl_cert(server_ip)

            return self._generate_mkcert_cert(cert_file, key_file, server_ip)

        print("[SSL] mkcert not found, falling back to openssl")
        return self._generate_openssl_cert(server_ip)

    def _generate_mkcert_cert(
        self,
        cert_file: Path,
        key_file: Path,
        server_ip: Optional[str] = None,
    ) -> tuple[str, str]:
        san_names = ["localhost", "127.0.0.1"]
        if server_ip:
            san_names.insert(0, server_ip)

        mkcert = self._find_mkcert()
        print(f"[SSL] Generating CA-trusted cert via mkcert for: {', '.join(san_names)}")

        try:
            subprocess.run(
                [
                    mkcert,
                    "-cert-file", str(cert_file),
                    "-key-file", str(key_file),
                ] + san_names,
                check=True,
                capture_output=True,
                text=True,
            )
            os.chmod(key_file, 0o600)
            print(f"[SSL] Certificate saved: {cert_file}")
            print(f"[SSL] Key saved: {key_file}")
            return str(cert_file), str(key_file)
        except subprocess.CalledProcessError as e:
            print(f"[SSL] mkcert failed: {e.stderr}")
            print("[SSL] Falling back to openssl")
            return self._generate_openssl_cert(server_ip)

    def _generate_openssl_cert(
        self,
        server_ip: Optional[str] = None,
    ) -> tuple[str, str]:
        cert_file = self.output_dir / "vscode-remote.crt"
        key_file = self.output_dir / "vscode-remote.key"

        if cert_file.exists() and key_file.exists():
            print(f"[SSL] Reusing existing cert: {cert_file}")
            return str(cert_file), str(key_file)

        print("[SSL] Generating self-signed cert via openssl...")

        key_size = 2048
        san_parts = ["DNS:localhost"]
        if server_ip:
            san_parts.insert(0, f"IP:{server_ip}")
        san_str = ",".join(san_parts)

        conf_content = f"""[req]
default_bits = {key_size}
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = vscode-remote

[v3_req]
subjectAltName = {san_str}
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
"""

        conf_file = self.output_dir / "vscode-remote.conf"
        conf_file.write_text(conf_content)

        try:
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-nodes",
                    "-days", "365",
                    "-newkey", f"rsa:{key_size}",
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
                f"Failed to generate SSL cert: {e.stderr}"
            ) from e
        finally:
            conf_file.unlink(missing_ok=True)

    def delete_cert(self) -> None:
        for name in ["vscode-remote"]:
            for ext in (".pem", "-key.pem", ".crt", ".key", ".conf"):
                p = self.output_dir / f"{name}{ext}"
                if p.exists():
                    p.unlink()
                    print(f"[SSL] Deleted: {p}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate SSL certs for VS Code Remote")
    parser.add_argument("--ip", type=str, help="External IP for SAN")
    parser.add_argument("--output-dir", type=str, default="/etc/nginx/ssl")
    args = parser.parse_args()

    gen = SSLCertificateGenerator(output_dir=args.output_dir)
    cert, key = gen.generate_server_cert(server_ip=args.ip)

    print(f"\n  ssl_certificate {cert};")
    print(f"  ssl_certificate_key {key};")


if __name__ == "__main__":
    main()
