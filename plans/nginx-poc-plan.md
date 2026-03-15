# Nginx Configuration Generator - Proof of Concept Plan

## Overview

Create a proof of concept (POC) for nginx configuration generation in the vscode-remote example. This POC will demonstrate automatic nginx site-available/site-enabled configuration generation for sandbox endpoints.

## POC Goals

1. Generate nginx configuration for a single sandbox instance
2. Use a random string as the server name (subdomain)
3. Create site-available configuration file
4. Create symlink to sites-enabled
5. Reload nginx to apply configuration
6. Test that the proxy works correctly

## Implementation Plan

### Step 1: Create Nginx Configuration Generator Module

**File**: `examples/vscode-remote/nginx_config.py`

**Responsibilities**:
- Generate nginx configuration file for a sandbox endpoint
- Create site-available configuration
- Create symlink to sites-enabled
- Reload nginx

**API**:

```python
class NginxConfigGenerator:
    """Generate nginx configuration for sandbox endpoints."""

    def __init__(
        self,
        sites_available_dir: str = "/etc/nginx/sites-available",
        sites_enabled_dir: str = "/etc/nginx/sites-enabled",
        reload_command: str = "sudo nginx -s reload",
    ):
        """Initialize nginx configuration generator."""

    def generate_config(
        self,
        server_name: str,
        upstream_host: str,
        upstream_port: int,
        use_https: bool = False,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
    ) -> str:
        """
        Generate nginx configuration file.

        Args:
            server_name: Server name (domain or subdomain)
            upstream_host: Host to proxy to (e.g., 127.0.0.1)
            upstream_port: Port to proxy to
            use_https: Whether to use HTTPS
            cert_path: Path to SSL certificate
            key_path: Path to SSL key

        Returns:
            Path to generated configuration file
        """

    def enable_config(self, config_path: str) -> None:
        """
        Enable nginx configuration by creating symlink.

        Args:
            config_path: Path to configuration file in sites-available
        """

    def disable_config(self, config_path: str) -> None:
        """
        Disable nginx configuration by removing symlink.

        Args:
            config_path: Path to configuration file in sites-available
        """

    def reload_nginx(self) -> None:
        """Reload nginx configuration."""

    def test_config(self) -> bool:
        """Test nginx configuration validity."""
```

### Step 2: Create SSL Certificate Generator

**File**: `examples/vscode-remote/ssl_cert.py`

**Responsibilities**:
- Generate self-signed SSL certificates
- Generate random subdomain names

**API**:

```python
class SSLCertificateGenerator:
    """Generate self-signed SSL certificates."""

    def generate_self_signed_cert(
        self,
        server_name: str,
        output_dir: str = "/etc/nginx/ssl",
    ) -> tuple[str, str]:
        """
        Generate self-signed certificate.

        Args:
            server_name: Server name (domain or subdomain)
            output_dir: Directory to save certificate files

        Returns:
            Tuple of (cert_path, key_path)
        """

    def generate_random_subdomain(self, length: int = 8) -> str:
        """
        Generate random subdomain name.

        Args:
            length: Length of random string

        Returns:
            Random subdomain name (e.g., "abc12345.localhost")
        """
```

### Step 3: Modify vscode-remote/main.py

**Changes**:

1. Add nginx configuration generation option
2. Add SSL certificate generation option
3. Integrate nginx config generation after sandbox creation
4. Add cleanup on sandbox deletion

**New Arguments**:

```python
parser.add_argument(
    "--use-nginx",
    action="store_true",
    default=False,
    help="Use nginx reverse proxy for sandbox endpoints",
)

parser.add_argument(
    "--nginx-domain",
    type=str,
    default="localhost",
    help="Base domain for nginx subdomains (default: localhost)",
)
```

**Integration Point**:

After sandbox is created and code-server is started:

```python
if args.use_nginx:
    # Generate random subdomain
    subdomain = ssl_cert_gen.generate_random_subdomain()
    server_name = f"{subdomain}.{args.nginx_domain}"

    # Generate SSL certificate
    cert_path, key_path = ssl_cert_gen.generate_self_signed_cert(
        server_name=server_name,
    )

    # Generate nginx configuration
    config_path = nginx_gen.generate_config(
        server_name=server_name,
        upstream_host="127.0.0.1",
        upstream_port=port,
        use_https=True,
        cert_path=cert_path,
        key_path=key_path,
    )

    # Enable configuration
    nginx_gen.enable_config(config_path)

    # Reload nginx
    nginx_gen.reload_nginx()

    print(f"[Nginx] Configuration created: {config_path}")
    print(f"[Nginx] Access via: https://{server_name}/")
```

### Step 4: Nginx Configuration Templates

**HTTP Template**:

```nginx
server {
    listen 80;
    server_name {server_name};

    location / {
        proxy_pass http://{upstream_host}:{upstream_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**HTTPS Template**:

```nginx
server {
    listen 443 ssl http2;
    server_name {server_name};

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://{upstream_host}:{upstream_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Testing Plan

### Test 1: Single Instance with Nginx

```bash
# Run with nginx proxy
uv run python examples/vscode-remote/main.py \
    --instances 1 \
    --use-nginx \
    --nginx-domain localhost \
    --workspace test
```

**Expected Results**:
- Sandbox created successfully
- Nginx configuration generated in `/etc/nginx/sites-available/`
- Symlink created in `/etc/nginx/sites-enabled/`
- Nginx reloaded successfully
- Accessible via `https://<random-subdomain>.localhost/`

### Test 2: Cleanup

```bash
# Stop the script (Ctrl+C)
# Verify nginx configuration is removed
ls /etc/nginx/sites-enabled/
ls /etc/nginx/sites-available/
```

**Expected Results**:
- Nginx configuration files removed
- Symlinks removed
- No orphaned configurations

### Test 3: Multiple Instances (Extension)

After POC is verified, extend to multiple instances:

```bash
uv run python examples/vscode-remote/main.py \
    --instances 3 \
    --use-nginx \
    --nginx-domain localhost \
    --workspace test
```

**Expected Results**:
- 3 sandboxes created
- 3 nginx configurations generated
- 3 unique subdomains
- All accessible via their respective URLs

## Prerequisites

### 1. Install nginx

```bash
sudo apt-get update
sudo apt-get install nginx
```

### 2. Create directories

```bash
sudo mkdir -p /etc/nginx/sites-available
sudo mkdir -p /etc/nginx/sites-enabled
sudo mkdir -p /etc/nginx/ssl
```

### 3. Set permissions

```bash
sudo chown -R $USER:$USER /etc/nginx/sites-available
sudo chown -R $USER:$USER /etc/nginx/sites-enabled
sudo chown -R $USER:$USER /etc/nginx/ssl
```

### 4. Configure nginx to include sites-enabled

Add to `/etc/nginx/nginx.conf`:

```nginx
http {
    # ... existing config ...

    # Include site configurations
    include /etc/nginx/sites-enabled/*;
}
```

### 5. Test nginx

```bash
sudo nginx -t
sudo systemctl restart nginx
```

## File Structure

```
examples/vscode-remote/
├── main.py                 # Modified to support nginx
├── nginx_config.py         # NEW: Nginx configuration generator
├── ssl_cert.py            # NEW: SSL certificate generator
├── generate-certs.py      # Existing: mkcert certificate generator
├── Dockerfile             # Existing
└── README.md              # Update with nginx instructions
```

## Success Criteria

1. ✅ Nginx configuration file generated correctly
2. ✅ Symlink created in sites-enabled
3. ✅ Nginx reloaded without errors
4. ✅ Sandbox accessible via nginx proxy
5. ✅ HTTPS works with self-signed certificate
6. ✅ Cleanup removes all configurations
7. ✅ Works with multiple instances (extension)

## Next Steps After POC

1. **Verify POC works** - Test with single instance
2. **Extend to multi-instance** - Add support for multiple sandboxes
3. **Add certificate validation** - Check certificate expiration
4. **Add error handling** - Graceful failure if nginx not available
5. **Add logging** - Detailed logging for debugging
6. **Update documentation** - README with setup instructions
7. **Consider production use** - Certbot integration for real domains
