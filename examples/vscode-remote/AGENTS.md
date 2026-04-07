# VS Code Remote Example AGENTS

Use this file for all work in `examples/vscode-remote/`. Reference template: `examples/vscode/`.
This is a hackathon-focused multi-instance VS Code remote development tool with nginx
reverse proxy, per-instance SSL, and persistent workspace support.

## Scope

- `examples/vscode-remote/**` — all files in this directory
- Reference: `examples/vscode/main.py` — simple single-instance pattern (87 lines)

## Commands

```bash
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

# Run the example (single instance)
uv run python examples/vscode-remote/main.py --instances 1 --workspace test

# Run with nginx proxy
uv run python examples/vscode-remote/main.py --instances 1 --use-nginx --nginx-domain localhost

# Generate self-signed certs
uv run python examples/vscode-remote/generate-certs.py
```

## Code Style

### Language & Formatting
- **Python 3.10+** (project minimum)
- **ruff** for lint and format; line-length = 88 (follows SDK convention)
- **pyright** with `typeCheckingMode = "standard"` for type checking
- **Apache 2.0 license header** required on every file

### Imports
Order: stdlib → third-party → local. Use explicit imports:
```python
# Standard library
import asyncio
from pathlib import Path
from typing import Optional

# Third-party
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig

# Local (relative imports within this example)
from nginx_config import NginxConfigGenerator
from ssl_cert import SSLCertificateGenerator
```

### Type Hints
Required on all function signatures and class attributes:
```python
async def create_instance(
    instance_id: int,
    workspace: str,
    port: int,
    config: ConnectionConfig,
    https: bool = False,
) -> SandboxInstance:
```
Use `Optional[T]`, `list[T]`, `tuple[str, ...]` syntax (Python 3.10+).

### Naming Conventions
- Functions/methods: `snake_case`
- Classes: `PascalCase`
- Constants / class attrs: `UPPER_SNAKE_CASE`
- Private internals: `_leading_underscore`
- CLI flags: `--kebab-case`

### Docstrings
Google-style on all public classes and functions. Module docstring at top of every file:
```python
"""One-line summary.

Longer description if needed.

Usage:
    uv run python examples/vscode-remote/main.py --instances 3
"""
```

### Error Handling
- Raise with descriptive, actionable messages
- Chain exceptions: `raise RuntimeError(...) from e`
- Prefer specific exception types over generic `Exception`
- Validate inputs early at function entry

### Async Patterns
- All sandbox operations are async — use `await`
- Use `asyncio.gather()` for concurrent instance creation
- Use `RunCommandOpts(background=True)` for long-running processes (code-server)
- Always use `try/finally` for cleanup (kill sandboxes, remove nginx configs)

### Logging (CLI Tools)
This is a CLI example — use `print()` with prefixed labels:
```python
print(f"[Instance {instance_id}] Starting code-server on port {port}")
print(f"[Nginx] Configuration created: {config_path}")
print(f"[SSL] Certificate saved: {cert_path}")
```

## Architecture

### Core Models
- **`SandboxInstance` dataclass**: holds instance metadata — id, workspace, port, sandbox object, endpoint URL, HTTPS state, cert/key paths, nginx config path, random URL string

### Key Classes
- **`NginxConfigGenerator`**: generates per-instance nginx configs (HTTP/HTTPS templates), manages sites-available → sites-enabled symlinks, reloads nginx
- **`SSLCertificateGenerator`**: creates self-signed RSA certs with SAN extensions using the `cryptography` library; saves to configurable output directory

### Two Network Modes

| Mode | Port Strategy | URL Format | Nginx Location |
|------|---------------|------------|----------------|
| **Bridge** | Random 40000–60000 | `http://127.0.0.1:{port}/proxy/{cs-port}/` | `/{random_string}/` |
| **Host** | Sequential from 8443 | `127.0.0.1:{port}` | `/` |

### Nginx Config Templates
- **HTTPS template**: listens 443 ssl http2, includes cert/key paths, TLSv1.2+TLSv1.3, WebSocket upgrade headers, `X-Forwarded-*` headers, `Service-Worker-Allowed /` header, 86400s timeouts
- **HTTP template**: listens 80, same proxy headers without SSL

### Workspace Persistence
Workspaces are stored locally and correlated by identity:
- Single user: `{storage_root}/{username}/{workspace_name}/`
- Group context: `{storage_root}/{group_name}/{username}/{workspace_name}/`

### Certificate Flow
1. Generate cert on **host** via `SSLCertificateGenerator.generate_self_signed_cert()`
2. (Or use mkcert via `generate-certs.py` for local dev with browser-trusted certs)
3. Inject into container at `/tmp/cert.pem` and `/tmp/key.pem` via `_inject_certificate()`
4. code-server launches with `--cert` and `--cert-key` flags
5. nginx uses the same (or its own) cert for terminating external HTTPS

### Proxy Mode Auto-Detection
When endpoint host is an IP address (EIP) and HTTPS is requested:
- Automatically switches to server-proxy mode (`use_server_proxy=True`)
- code-server runs HTTP internally; proxy terminates SSL
- Override with `--force-https` to use direct EIP + HTTPS (requires matching cert)

## Guardrails

### Must Always
- Generate SSL certificates on the **host**, never inside containers
- Clean up nginx configs and kill sandboxes in `finally` blocks
- Use non-root `vscode` user in containers; respect filesystem permissions
- Include Apache 2.0 license header on every new file

### Must Never
- Commit secrets, API keys, or certificate key files to the repository
- Generate self-signed certs inside sandbox containers
- Mix unrelated changes (e.g., server core + example UI) in one PR
- Remove `--auth none` without a replacement auth mechanism (hackathon UX depends on it)

### Known Gotchas

**Service Worker SSL Error** (the error you're seeing):
```
SecurityError: Failed to register a ServiceWorker for scope
('https://{ip}/{rand}/proxy/{port}/.../pre/') with script ('...service-worker.js?...&remoteAuthority={ip}'):
An SSL certificate error occurred when fetching the script.
```
- **Cause**: When using path-based nginx proxy (`/{random_string}/proxy/{port}/`), the service worker
  script URL's origin doesn't match the page scope due to SSL cert mismatch or protocol downgrade.
- **Fix options**:
  1. Ensure nginx SSL cert covers the IP address (add as SAN)
  2. Use `proxy_ssl_verify off` only if backend is HTTP (not sufficient for SW registration)
  3. Use subdomain-based routing (one nginx `server` block per instance) instead of path-based
  4. Set `add_header Service-Worker-Allowed /;` always (already in template)
  5. For hackathons: simplest fix is host mode with direct port mapping (`127.0.0.1:8443`)

**Environment Variables**:
- `SANDBOX_DOMAIN` — server address (default: `localhost:8080`)
- `SANDBOX_API_KEY` — optional API key
- `SANDBOX_IMAGE` — Docker image (default: `opensandbox/vscode:latest`)
- `PYTHON_VERSION` — Python version in sandbox (default: `3.11`)

**Prerequisites** (for hackathon setup script):
```
python3 python3-venv python3-pip nginx docker.io docker-buildx
```

## File Map

| File | Purpose |
|------|---------|
| `main.py` | Entry point; argparse CLI; instance orchestration; cert injection |
| `nginx_config.py` | `NginxConfigGenerator` class; HTTP/HTTPS templates; symlink management |
| `ssl_cert.py` | `SSLCertificateGenerator` class; self-signed cert creation via cryptography |
| `generate-certs.py` | Standalone mkcert-based cert generation helper (local dev) |
| `Dockerfile` | Sandbox image: python:3.12-slim + code-server + non-root vscode user |
| `../vscode/main.py` | Reference template: single-instance, minimal, ~87 lines |
