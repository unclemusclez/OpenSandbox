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

This module provides functionality to generate self-signed SSL certificates
for development and testing purposes. It uses Python's cryptography library
to create certificates with proper Subject Alternative Names (SAN).

Usage:
    from examples.vscode_remote.ssl_cert import SSLCertificateGenerator

    generator = SSLCertificateGenerator()
    cert_path, key_path = generator.generate_self_signed_cert(
        server_name="abc12345.localhost",
        output_dir="/etc/nginx/ssl",
    )
    subdomain = generator.generate_random_subdomain()
"""

import os
import random
import string
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtensionOID
except ImportError:
    raise ImportError(
        "cryptography library is required. " "Install with: pip install cryptography"
    )


class SSLCertificateGenerator:
    """
    Generate self-signed SSL certificates for development.

    This class handles:
    - Generating RSA private keys
    - Creating X.509 certificates
    - Adding Subject Alternative Names (SAN)
    - Saving certificates and keys to files
    - Generating random subdomain names
    """

    # Certificate validity period (default: 1 year)
    CERT_VALIDITY_DAYS = 365

    # RSA key size (default: 2048 bits)
    KEY_SIZE = 2048

    def __init__(
        self,
        output_dir: str = "/etc/nginx/ssl",
        key_size: int = 2048,
        cert_validity_days: int = 365,
    ):
        """
        Initialize SSL certificate generator.

        Args:
            output_dir: Directory to save certificate files
            key_size: RSA key size in bits (default: 2048)
            cert_validity_days: Certificate validity in days (default: 365)
        """
        self.output_dir = Path(output_dir)
        self.key_size = key_size
        self.cert_validity_days = cert_validity_days

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_self_signed_cert(
        self,
        server_name: str,
        output_dir: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Generate self-signed certificate.

        Args:
            server_name: Server name (domain or subdomain)
            output_dir: Directory to save certificate files (default: from __init__)

        Returns:
            Tuple of (cert_path, key_path)

        Raises:
            RuntimeError: If certificate generation fails
        """
        # Use provided output_dir or default
        cert_dir = Path(output_dir) if output_dir else self.output_dir
        cert_dir.mkdir(parents=True, exist_ok=True)

        print(f"[SSL] Generating self-signed certificate for: {server_name}")

        try:
            # Generate private key
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=self.key_size,
            )

            # Create certificate subject
            subject = x509.Name(
                [
                    x509.NameAttribute(
                        NameOID.COMMON_NAME,
                        server_name,
                    ),
                ]
            )

            # Create certificate builder
            cert_builder = x509.CertificateBuilder()
            cert_builder = cert_builder.subject_name(subject)
            cert_builder = cert_builder.issuer_name(subject)
            cert_builder = cert_builder.public_key(
                private_key.public_key(),
            )
            cert_builder = cert_builder.serial_number(
                x509.random_serial_number(),
            )
            cert_builder = cert_builder.not_valid_before(
                datetime.utcnow(),
            )
            cert_builder = cert_builder.not_valid_after(
                datetime.utcnow() + timedelta(days=self.cert_validity_days),
            )

            # Add Subject Alternative Names (SAN)
            san_list = [x509.DNSName(server_name)]

            # Add IP address if server_name is an IP
            try:
                # Try to parse as IP address
                from ipaddress import ip_address

                ip = ip_address(server_name)
                san_list.append(x509.IPAddress(ip))
            except ValueError:
                # Not an IP address, skip
                pass

            # Add SAN extension
            cert_builder = cert_builder.add_extension(
                x509.SubjectAlternativeName(san_list),
                critical=False,
            )

            # Add basic constraints
            cert_builder = cert_builder.add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )

            # Add key usage
            cert_builder = cert_builder.add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    key_cert_sign=False,
                    key_agreement=False,
                    content_commitment=False,
                    data_encipherment=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )

            # Add extended key usage
            cert_builder = cert_builder.add_extension(
                x509.ExtendedKeyUsage(
                    [
                        x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                        x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                    ]
                ),
                critical=False,
            )

            # Sign certificate
            certificate = cert_builder.sign(
                private_key,
                hashes.SHA256(),
            )

            # Save private key
            key_filename = f"{server_name.replace('.', '-')}.key"
            key_path = cert_dir / key_filename

            with open(key_path, "wb") as f:
                f.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.TraditionalOpenSSL,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )

            # Save certificate
            cert_filename = f"{server_name.replace('.', '-')}.crt"
            cert_path = cert_dir / cert_filename

            with open(cert_path, "wb") as f:
                f.write(
                    certificate.public_bytes(
                        encoding=serialization.Encoding.PEM,
                    )
                )

            # Set restrictive permissions on key file
            os.chmod(key_path, 0o600)

            print(f"[SSL] Certificate saved: {cert_path}")
            print(f"[SSL] Key saved: {key_path}")

            return str(cert_path), str(key_path)

        except Exception as e:
            raise RuntimeError(f"Failed to generate SSL certificate: {e}") from e

    def generate_random_subdomain(
        self,
        length: int = 8,
        base_domain: str = "localhost",
    ) -> str:
        """
        Generate random subdomain name.

        Args:
            length: Length of random string (default: 8)
            base_domain: Base domain (default: localhost)

        Returns:
            Random subdomain name (e.g., "abc12345.localhost")
        """
        # Generate random string
        chars = string.ascii_lowercase + string.digits
        random_str = "".join(random.choice(chars) for _ in range(length))

        # Create subdomain
        subdomain = f"{random_str}.{base_domain}"

        print(f"[SSL] Generated subdomain: {subdomain}")

        return subdomain

    def cert_exists(self, server_name: str, output_dir: Optional[str] = None) -> bool:
        """
        Check if certificate exists for server name.

        Args:
            server_name: Server name (domain or subdomain)
            output_dir: Directory to check (default: from __init__)

        Returns:
            True if certificate and key exist, False otherwise
        """
        cert_dir = Path(output_dir) if output_dir else self.output_dir

        cert_filename = f"{server_name.replace('.', '-')}.crt"
        key_filename = f"{server_name.replace('.', '-')}.key"

        cert_path = cert_dir / cert_filename
        key_path = cert_dir / key_filename

        return cert_path.exists() and key_path.exists()

    def delete_cert(self, server_name: str, output_dir: Optional[str] = None) -> None:
        """
        Delete certificate and key for server name.

        Args:
            server_name: Server name (domain or subdomain)
            output_dir: Directory to check (default: from __init__)
        """
        cert_dir = Path(output_dir) if output_dir else self.output_dir

        cert_filename = f"{server_name.replace('.', '-')}.crt"
        key_filename = f"{server_name.replace('.', '-')}.key"

        cert_path = cert_dir / cert_filename
        key_path = cert_dir / key_filename

        try:
            if cert_path.exists():
                cert_path.unlink()
                print(f"[SSL] Deleted certificate: {cert_path}")

            if key_path.exists():
                key_path.unlink()
                print(f"[SSL] Deleted key: {key_path}")
        except OSError as e:
            print(f"[SSL] Warning: Failed to delete certificate: {e}")

    def cleanup_certs(
        self, pattern: str = "*.crt", output_dir: Optional[str] = None
    ) -> None:
        """
        Remove all certificates matching a pattern.

        Args:
            pattern: Glob pattern for certificate files (default: *.crt)
            output_dir: Directory to check (default: from __init__)
        """
        cert_dir = Path(output_dir) if output_dir else self.output_dir

        # Find all matching certificates
        certs = list(cert_dir.glob(pattern))

        if not certs:
            print(f"[SSL] No certificates found matching pattern: {pattern}")
            return

        print(f"[SSL] Found {len(certs)} certificate(s) to clean up")

        # Delete each certificate and its key
        for cert_path in certs:
            server_name = cert_path.stem.replace("-", ".")
            self.delete_cert(server_name, output_dir=str(cert_dir))


def main():
    """Main function for testing SSL certificate generator."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate self-signed SSL certificates"
    )
    parser.add_argument(
        "--server-name",
        type=str,
        help="Server name (domain or subdomain)",
    )
    parser.add_argument(
        "--random-subdomain",
        action="store_true",
        help="Generate random subdomain",
    )
    parser.add_argument(
        "--subdomain-length",
        type=int,
        default=8,
        help="Length of random subdomain (default: 8)",
    )
    parser.add_argument(
        "--base-domain",
        type=str,
        default="localhost",
        help="Base domain for subdomain (default: localhost)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="/etc/nginx/ssl",
        help="Directory to save certificates (default: /etc/nginx/ssl)",
    )
    parser.add_argument(
        "--key-size",
        type=int,
        default=2048,
        help="RSA key size in bits (default: 2048)",
    )
    parser.add_argument(
        "--validity-days",
        type=int,
        default=365,
        help="Certificate validity in days (default: 365)",
    )

    args = parser.parse_args()

    # Create generator
    generator = SSLCertificateGenerator(
        output_dir=args.output_dir,
        key_size=args.key_size,
        cert_validity_days=args.validity_days,
    )

    # Generate subdomain if requested
    if args.random_subdomain:
        server_name = generator.generate_random_subdomain(
            length=args.subdomain_length,
            base_domain=args.base_domain,
        )
    elif args.server_name:
        server_name = args.server_name
    else:
        parser.error("Either --server-name or --random-subdomain is required")

    # Generate certificate
    cert_path, key_path = generator.generate_self_signed_cert(
        server_name=server_name,
        output_dir=args.output_dir,
    )

    print(f"\nCertificate: {cert_path}")
    print(f"Key: {key_path}")
    print(f"\nTo use with nginx:")
    print(f"  ssl_certificate {cert_path};")
    print(f"  ssl_certificate_key {key_path};")


if __name__ == "__main__":
    main()
