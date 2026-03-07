# VS Code Remote - Multi-Instance Example

This example demonstrates how to run multiple VS Code sandbox instances concurrently, each with its own workspace and code-server instance.

## Overview

The VS Code Remote example extends the basic VS Code example by supporting:

- **Multiple concurrent instances**: Run multiple VS Code sandboxes simultaneously
- **Workspace separation**: Each instance has its own isolated workspace directory
- **Port allocation**: Automatic port allocation for each instance (e.g., 8443, 8444, 8445)
- **Configurable timeout**: Control how long sandboxes remain active

## SSL/TLS Architecture

This example supports two HTTPS modes:

### Mode 1: Proxy-Based HTTPS (Default)

The OpenSandbox server acts as a proxy that can terminate SSL at the edge. This architecture enables:

- **WebSockets support**: Required for real-time features like live share and terminal
- **Plugin support**: Many VS Code extensions require HTTPS to function properly
- **Secure connections**: All traffic is encrypted between the browser and the OpenSandbox server

#### How Proxy-Based HTTPS Works

1. **code-server** runs inside the sandbox over plain HTTP (e.g., `http://localhost:8443`)
2. **OpenSandbox server** proxies requests from the browser to the sandbox
3. **SSL termination** happens at the OpenSandbox server edge (if configured)

> **Important**: If your OpenSandbox server is not configured with SSL, use `http://` URLs. The `SSL_ERROR_RX_RECORD_TOO_LONG` error occurs when trying to access an HTTP endpoint with HTTPS.

### Mode 2: mkcert Local Development HTTPS

For local development, you can run code-server directly over HTTPS using mkcert-generated certificates. This is useful for testing VS Code extensions that require HTTPS.

#### Quick Start with mkcert

```shell
# Install mkcert (if not already installed)
# Windows: winget install FiloSottile.mkcert
# macOS: brew install mkcert
# Linux: curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64" && sudo install mkcert -v /usr/local/bin/

# Install the local CA
mkcert --install

# Generate wildcard certificate (*.localhost)
uv run python examples/vscode-remote/generate-certs.py

# Run VS Code instances with HTTPS
uv run python examples/vscode-remote/main.py --instances 3 --https \
  --cert ./certs/localhost.pem --key ./certs/localhost-key.pem
```

#### Per-Sandbox Certificates

For more granular control, generate individual certificates per sandbox:

```shell
# Generate per-sandbox certificates
uv run python examples/vscode-remote/generate-certs.py --per-sandbox \
  --sandbox vscode-8443 --sandbox vscode-8444 --sandbox vscode-8445

# Run with per-sandbox certificates
uv run python examples/vscode-remote/main.py --instances 3 --https \
  --cert ./certs/vscode-8443.pem --key ./certs/vscode-8443-key.pem \
  --cert ./certs/vscode-8444.pem --key ./certs/vscode-8444-key.pem \
  --cert ./certs/vscode-8445.pem --key ./certs/vscode-8445-key.pem
```

#### How mkcert HTTPS Works

1. **mkcert** creates a local CA and generates certificates trusted by your browser
2. **code-server** runs inside the sandbox with `--cert` and `--cert-key` flags
3. **Browser** trusts the mkcert CA (after installing it once)

> **Note**: This mode is only useful for local development. The mkcert CA must be installed on your machine for browsers to trust the certificates.

#### Security Considerations

- **Local CA only**: mkcert certificates are only trusted on your local machine
- **Not for production**: Do not use mkcert in production environments
- **Install CA once**: Run `mkcert --install` once to install the local CA
- **Certificate expiration**: mkcert certificates expire after 1-2 years; regenerate as needed

## External Access Configuration

By default, sandboxes are accessible via the OpenSandbox server's proxy. The URLs you see (e.g., `http://127.0.0.1:43876/proxy/8443/`) are proxied through the server. To make them reachable from the outside world, you have several options:

### Option 1: Public Domain with OpenSandbox Server

Configure your OpenSandbox server with a public domain in `~/.sandbox.toml`:

```toml
[server]
domain = "your-domain.com"  # Public domain
bind_address = "0.0.0.0"    # Listen on all interfaces
port = 8080
```

Then access via:
```
https://your-domain.com/sandbox/{sandbox-id}/proxy/{port}/
```

The URLs will be HTTPS because the OpenSandbox server handles SSL termination at the proxy level.

### Option 2: Port Forwarding (Local Development)

For local development, use SSH port forwarding:

```shell
# Forward sandbox ports to local machine
ssh -L 8443:localhost:43876 user@opensandbox-server
ssh -L 8444:localhost:58260 user@opensandbox-server
ssh -L 8445:localhost:42981 user@opensandbox-server
```

Then access via `http://localhost:8443/`, `http://localhost:8444/`, etc.

### Option 3: Reverse Proxy with Public IPs

Configure a reverse proxy (nginx, Traefik) to expose sandbox ports:

```nginx
# nginx configuration
location /vscode-1/ {
    proxy_pass http://127.0.0.1:43876/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}

location /vscode-2/ {
    proxy_pass http://127.0.0.1:58260/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

### Option 4: Kubernetes Ingress

If running on Kubernetes, configure Ingress resources:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: vscode-ingress
spec:
  rules:
  - host: vscode.example.com
    http:
      paths:
      - path: /vscode-1
        pathType: Prefix
        backend:
          service:
            name: sandbox-1
            port:
              number: 8443
```

## Configure SSL for OpenSandbox Server

The OpenSandbox server itself runs over HTTP. To enable HTTPS, you need to place a reverse proxy in front of it. Here's how to configure nginx with SSL:

### Step 1: Generate SSL Certificates

Using Let's Encrypt (recommended for production):
```bash
# Install certbot
sudo apt-get install certbot

# Obtain SSL certificate
sudo certbot certonly --standalone -d your-domain.com
```

Using self-signed certificates (for development):
```bash
# Generate private key
openssl genrsa -out server.key 2048

# Generate certificate
openssl req -new -x509 -key server.key -out server.crt -days 365 -subj "/CN=localhost"
```

### Step 2: Configure nginx

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/server.crt;
    ssl_certificate_key /path/to/server.key;

    # SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # WebSocket support for code-server
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}
```

### Step 3: Start nginx

```bash
sudo nginx -t  # Test configuration
sudo systemctl start nginx
sudo systemctl enable nginx
```

## Build the VS Code Sandbox Image

The Dockerfile in this directory builds a sandbox image with code-server pre-installed:

```shell
cd examples/vscode-remote
docker build -t opensandbox/vscode:latest .
```

This image includes:
- code-server (VS Code Web) pre-installed
- Non-root user (vscode) for security
- Workspace directory at `/workspace`

## Start OpenSandbox Server [local]

Pre-pull the VS Code image:

```shell
docker pull sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/vscode:latest
```

Start the local OpenSandbox server:

```shell
uv pip install opensandbox-server
opensandbox-server init-config ~/.sandbox.toml --example docker
opensandbox-server
```

## Create and Access Multiple VS Code Sandboxes

### Basic Usage

```shell
# Install OpenSandbox package
uv pip install opensandbox

# Run 3 concurrent VS Code instances
uv run python examples/vscode-remote/main.py --instances 3
```

### Custom Configuration

```shell
# Run 2 instances with custom workspace and starting port
uv run python examples/vscode-remote/main.py \
  --instances 2 \
  --workspace myproject \
  --port 8443

# Run with custom timeout (30 minutes)
uv run python examples/vscode-remote/main.py \
  --instances 2 \
  --timeout 30

# Run with custom domain and API key
SANDBOX_DOMAIN="your-domain.com" \
SANDBOX_API_KEY="your-api-key" \
uv run python examples/vscode-remote/main.py \
  --instances 2
```

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--instances` | Number of concurrent sandbox instances | `1` |
| `--workspace` | Workspace name for all instances | `default` |
| `--port` | Starting port for code-server instances | `8443` |
| `--timeout` | Timeout in minutes to keep sandboxes alive | `10` |
| `--domain` | Sandbox domain | `localhost:8080` |
| `--api-key` | Sandbox API key | (none) |
| `--image` | Docker image for sandbox | `opensandbox/vscode:latest` |
| `--python-version` | Python version for the sandbox | `3.11` |
| `--https` | Use HTTPS (requires --cert and --key flags) | `false` |
| `--cert` | Certificate file path (can be specified multiple times) | (none) |
| `--key` | Certificate key file path (can be specified multiple times) | (none) |

### HTTPS Usage

If you have generated certificates using mkcert, use the `--https` flag with `--cert` and `--key`:

```shell
# Use wildcard certificate for all instances
uv run python examples/vscode-remote/main.py --instances 3 --https \
  --cert ./certs/localhost.pem --key ./certs/localhost-key.pem

# Use per-sandbox certificates
uv run python examples/vscode-remote/main.py --instances 3 --https \
  --cert ./certs/vscode-8443.pem --key ./certs/vscode-8443-key.pem \
  --cert ./certs/vscode-8444.pem --key ./certs/vscode-8444-key.pem \
  --cert ./certs/vscode-8445.pem --key ./certs/vscode-8445-key.pem
```

### Example Output

```
Starting 3 VS Code sandbox instance(s)...
  Domain: localhost:8080
  Image: opensandbox/vscode:latest
  Workspace: default
  Port range: 8443 - 8445
  Timeout: 10 minutes
  HTTPS: Yes
  Certificate: ./certs/localhost.pem (wildcard)

============================================================
VS Code Web Endpoints (HTTPS - mkcert local CA)
============================================================

  Instance 1:
    Workspace: default
    Port: 8443
    URL: https://127.0.0.1:43876/proxy/8443/

  Instance 2:
    Workspace: default
    Port: 8444
    URL: https://127.0.0.1:58260/proxy/8444/

  Instance 3:
    Workspace: default
    Port: 8445
    URL: https://127.0.0.1:42981/proxy/8445/

Keeping sandboxes alive for 10 minutes. Press Ctrl+C to exit sooner.
```

> **Troubleshooting SSL Error**: If you see `SSL_ERROR_RX_RECORD_TOO_LONG` in your browser, it means you're trying to access an HTTP endpoint with HTTPS. The code-server instances run over plain HTTP internally. Use `http://` URLs for local development unless your OpenSandbox server is configured with SSL certificates.

## Use Cases

### 1. Team Collaboration

Run multiple instances for different team members, each with their own workspace:

```shell
# Instance for developer A
uv run python examples/vscode-remote/main.py \
  --instances 1 \
  --workspace dev-a \
  --port 8443

# Instance for developer B (run in another terminal)
uv run python examples/vscode-remote/main.py \
  --instances 1 \
  --workspace dev-b \
  --port 8444
```

### 2. Parallel Development Environments

Create separate environments for different projects:

```shell
# Project A environment
uv run python examples/vscode-remote/main.py \
  --instances 1 \
  --workspace project-a \
  --port 8443

# Project B environment
uv run python examples/vscode-remote/main.py \
  --instances 1 \
  --workspace project-b \
  --port 8444

# Project C environment
uv run python examples/vscode-remote/main.py \
  --instances 1 \
  --workspace project-c \
  --port 8445
```

### 3. Testing and QA

Run multiple instances for testing different configurations:

```shell
# Test instance with Python 3.10
uv run python examples/vscode-remote/main.py \
  --instances 1 \
  --workspace test-py310 \
  --python-version 3.10 \
  --port 8443

# Test instance with Python 3.11
uv run python examples/vscode-remote/main.py \
  --instances 1 \
  --workspace test-py311 \
  --python-version 3.11 \
  --port 8444

# Test instance with Python 3.12
uv run python examples/vscode-remote/main.py \
  --instances 1 \
  --workspace test-py312 \
  --python-version 3.12 \
  --port 8445
```

## Workspace Isolation

Each sandbox instance runs in an isolated environment:

- **File System**: Each instance has its own `/workspace/{workspace-name}` directory
- **Processes**: Each instance runs a separate code-server process
- **Network**: Each instance listens on a unique port
- **State**: Changes in one instance do not affect others

## Security Considerations

### Authentication

By default, code-server runs with authentication disabled (`--auth none`). For production use:

1. Use a reverse proxy with authentication (e.g., nginx, Traefik)
2. Enable code-server authentication with a password
3. Use HTTPS with proper TLS certificates

### Resource Limits

When running multiple instances, consider:

- **CPU**: Each sandbox consumes CPU resources
- **Memory**: Each sandbox consumes memory resources
- **Disk**: Each sandbox uses disk space for the workspace
- **Network**: Each instance requires a unique port

## Certificate Generation Script

The `generate-certs.py` script helps you generate mkcert certificates for local development:

```shell
# Install mkcert CA
uv run python examples/vscode-remote/generate-certs.py --install-ca

# Generate wildcard certificate (*.localhost)
uv run python examples/vscode-remote/generate-certs.py

# Generate per-sandbox certificates
uv run python examples/vscode-remote/generate-certs.py --per-sandbox \
  --sandbox vscode-8443 --sandbox vscode-8444 --sandbox vscode-8445

# Generate certificates for specific sandbox IDs
uv run python examples/vscode-remote/generate-certs.py --sandbox my-sandbox
```

## References

- [code-server (VS Code Web)](https://github.com/coder/code-server)
- [mkcert - Trusted local TLS certificates](https://github.com/FiloSottile/mkcert)
- [Original VS Code Example](../vscode/README.md)
- [OpenSandbox Documentation](../../docs/README.md)