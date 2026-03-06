# VS Code Remote - Multi-Instance Example

This example demonstrates how to run multiple VS Code sandbox instances concurrently, each with its own workspace and code-server instance.

## Overview

The VS Code Remote example extends the basic VS Code example by supporting:

- **Multiple concurrent instances**: Run multiple VS Code sandboxes simultaneously
- **Workspace separation**: Each instance has its own isolated workspace directory
- **Port allocation**: Automatic port allocation for each instance (e.g., 8443, 8444, 8445)
- **Configurable timeout**: Control how long sandboxes remain active

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

### Example Output

```
Starting 3 VS Code sandbox instance(s)...
  Domain: localhost:8080
  Image: opensandbox/vscode:latest
  Workspace: default
  Port range: 8443 - 8445
  Timeout: 10 minutes

============================================================
VS Code Web Endpoints:
============================================================

  Instance 1:
    Workspace: default
    Port: 8443
    URL: http://127.0.0.1:43876/proxy/8443/

  Instance 2:
    Workspace: default
    Port: 8444
    URL: http://127.0.0.1:58260/proxy/8444/

  Instance 3:
    Workspace: default
    Port: 8445
    URL: http://127.0.0.1:42981/proxy/8445/

Keeping sandboxes alive for 10 minutes. Press Ctrl+C to exit sooner.
```

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

## References

- [code-server (VS Code Web)](https://github.com/coder/code-server)
- [Original VS Code Example](../vscode/README.md)
- [OpenSandbox Documentation](../../docs/README.md)