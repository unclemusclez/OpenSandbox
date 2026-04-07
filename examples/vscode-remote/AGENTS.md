# VS Code Remote Example AGENTS

Use this file for all work in `examples/vscode-remote/`. Reference template: `examples/vscode/`.
This is a hackathon-focused multi-instance VS Code remote development tool with nginx
reverse proxy, per-instance SSL (via openssl), and persistent workspace support.

## Scope

- `examples/vscode-remote/**` — all files in this directory
- Reference: `examples/vscode/main.py` — simple single-instance pattern (87 lines)

## Commands

```bash
# One-time prerequisite installation (python3, nginx, docker, openssl, uv)
bash examples/vscode-remote/setup.sh

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run pyright

# Run all tests
uv run pytest

# Run a single test
uv run pytest tests/test_file.py::test_function_name -v

# Pre-commit hooks (project-level)
pre-commit run --all-files

# Build Docker image
docker build -t opensandbox/vscode:latest .

# Run: 3 instances with auto-generated nginx + SSL (bridge mode, subdomain URIs)
uv run python examples/vscode-remote/main.py --instances 3 --use-nginx

# Run: 1 instance in host mode (port -> /port/ URI path)
uv run python examples/vscode-remote/main.py --instances 1 --use-nginx --mode host

# Run: with custom SSL dir and server IP for SAN
uv run python examples/vscode-remote/main.py --instances 1 --use-nginx \
    --ssl-dir ./certs --server-ip 165.245.140.250

# Generate a single cert manually via openssl
uv run python examples/vscode-remote/ssl_cert.py --port 8443 --ip 165.245.140.250
```

## Code Style

### Language & Formatting
- **Python 3.10+** (project minimum)
- **ruff** for lint and format; line-length = 88 (follows SDK convention)
- **pyright** with `typeCheckingMode = "standard"` for type checking
- **Apache 2.0 license header** required on every file

### Imports
Order: stdlib → third-party → local:
```python
import asyncio
from pathlib import Path
from typing import Optional

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig

from nginx_config import NginxConfigGenerator
from ssl_cert import SSLCertificateGenerator
```

### Type Hints
Required on all function signatures. Use `Optional[T]`, `list[T]`, `tuple[str, ...]` syntax (Python 3.10+).

### Naming Conventions
- Functions/methods: `snake_case`
- Classes: `PascalCase`
- Constants / class attrs: `UPPER_SNAKE_CASE`
- Private internals: `_leading_underscore`
- CLI flags: `--kebab-case`

### Docstrings
Google-style on public classes/functions. Module docstring at top of every file.

### Error Handling
- Raise with descriptive messages; chain with `raise ... from e`
- Validate inputs early at function entry

### Async Patterns
- All sandbox operations are async — use `await`
- Use `asyncio.gather()` for concurrent instance creation
- Use `RunCommandOpts(background=True)` for long-running processes (code-server)
- Always use `try/finally` for cleanup (kill sandboxes, remove nginx configs)

### Logging (CLI Tools)
Use `print()` with prefixed labels: `[Instance 0]`, `[Nginx]`, `[SSL]`

## Architecture

### Core Model
- **`SandboxInstance` dataclass**: id, workspace, port, sandbox object, endpoint URL, https state,
  cert/key paths, nginx config path, url_path (URI path e.g. `/8443/`)

### Key Classes
- **`SSLCertificateGenerator`**: generates self-signed certs via **openssl CLI** (no pip deps).
  Two methods:
  - `generate_cert_for_port(port, server_ip)` — host mode, cert named `port-{port}.crt`
  - `generate_cert_for_subdomain(subdomain, server_ip)` — bridge mode, subdomain-based cert
  - Both embed server IP in SAN to fix Service Worker SSL errors.
- **`NginxConfigGenerator`**: generates per-instance nginx configs, manages sites-available/enabled
  symlinks, reloads nginx. Uses `location_path` param for URI-based routing.

### Two Network Modes

| Mode | Port Strategy | URI Path | Cert Name | Use Case |
|------|---------------|----------|-----------|----------|
| **Bridge** | Random 40000–60000 | `/<random>/` | `<subdomain>.crt` | Subdomain routing |
| **Host** | Sequential from 8443 | `/<port>/` | `port-<port>.crt` | Direct port mapping |

### Certificate Flow (openssl, no cryptography library)

1. On instance creation, `SSLCertificateGenerator` calls `openssl req -x509` via subprocess
2. Config file is generated inline with SAN entries (IP + DNS names)
3. Cert saved to `{ssl_dir}/port-{port}.crt` or `{ssl_dir}/{subdomain}.crt`
4. Nginx HTTPS template references the cert for SSL termination
5. code-server always runs **HTTP** inside containers; nginx terminates SSL externally

### Nginx HTTPS Template Features
- Listens 443 ssl http2
- TLSv1.2 + TLSv1.3, `HIGH:!aNULL:!MD5` ciphers
- WebSocket upgrade headers (`Upgrade`, `Connection "upgrade"`)
- `X-Forwarded-For`, `X-Forwarded-Proto https`, `proxy_redirect off`
- `add_header Service-Worker-Allowed /;` (fixes SW scope errors)
- `proxy_ssl_verify off;` (backend is HTTP)
- `proxy_read/send_timeout 86400` (24h for long-lived WS connections)

## Guardrails

### Must Always
- Generate SSL certs on the **host** via openssl, never inside containers
- Clean up nginx configs + kill sandboxes in `finally` blocks
- Use non-root `vscode` user in containers
- Include Apache 2.0 header on every new file
- Pass `--server-ip` when accessing via IP address (prevents SW SSL errors)

### Must Never
- Commit secrets, API keys, or `.key` files to the repository
- Generate certs inside sandbox containers
- Mix unrelated changes in one PR
- Remove `--auth none` without replacement (hackathon UX depends on it)
- Use the `cryptography` pip package (use openssl subprocess instead)

### Known Gotchas

**Service Worker SSL Error** (the error from the issue):
```
SecurityError: Failed to register a ServiceWorker for scope ('https://{ip}/{path}/.../pre/')
An SSL certificate error occurred when fetching the script.
```
- **Root cause**: SW script fetch fails because the cert doesn't cover the target IP/domain
- **Fix**: Pass `--server-ip <IP>` so the cert includes `IP:<ip>` in SAN extensions.
  The nginx template already includes `Service-Worker-Allowed /` and `proxy_ssl_verify off`.
- If still failing: use host mode (`--mode host`) which maps port → `/port/` URI directly

**Environment Variables**:
- `SANDBOX_DOMAIN` — server address (default: `localhost:8080`)
- `SANDBOX_API_KEY` — optional API key
- `SANDBOX_IMAGE` — Docker image (default: `opensandbox/vscode:latest`)
- `PYTHON_VERSION` — Python version in sandbox (default: `3.11`)
- `SSL_DIR` — override default `/etc/nginx/ssl`

## File Map

| File | Purpose |
|------|---------|
| `main.py` | Entry point; argparse CLI; instance orchestration; mode selection |
| `setup.sh` | One-time install: python3, nginx, docker.io, docker-buildx, openssl, uv |
| `nginx_config.py` | `NginxConfigGenerator`; HTTP/HTTPS templates with SW headers; symlink mgmt |
| `ssl_cert.py` | `SSLCertificateGenerator`; openssl-based cert generation (no pip deps) |
| `generate-certs.py` | Legacy mkcert helper (preserved for local dev with browser-trusted certs) |
| `Dockerfile` | Sandbox image: python:3.12-slim + code-server + non-root vscode user |
| `../vscode/main.py` | Reference template: single-instance, minimal, ~87 lines |
