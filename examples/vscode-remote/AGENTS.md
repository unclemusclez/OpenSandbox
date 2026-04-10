# VS Code Remote Example AGENTS

Use this file for all work in `examples/vscode-remote/`. Reference template: `examples/vscode/`.
This is a hackathon-focused multi-instance VS Code remote development tool with nginx
reverse proxy, per-instance SSL (via openssl), groups support, and persistent workspace support.

## Scope

- `examples/vscode-remote/**` — all files in this directory
- Reference: `examples/vscode/main.py` — simple single-instance pattern

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

# Build Docker image
docker build -t opensandbox/vscode:latest examples/vscode-remote/

# Run: all groups from groups.yaml with nginx + SSL
uv run python examples/vscode-remote/main.py --groups groups.yaml --use-nginx

# Run: single group
uv run python examples/vscode-remote/main.py --groups groups.yaml --group alpha --use-nginx

# Run: with secure per-user passwords
uv run python examples/vscode-remote/main.py --groups groups.yaml --use-nginx --secure

# Run: single instance without groups (like examples/vscode/main.py)
uv run python examples/vscode-remote/main.py --use-nginx

# Run: bridge mode (must match server's docker.network_mode)
uv run python examples/vscode-remote/main.py --groups groups.yaml --use-nginx --mode bridge

# Run: with custom SSL dir and server IP for SAN
uv run python examples/vscode-remote/main.py --use-nginx \
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
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import yaml

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
Use `print()` with prefixed labels: `[{group}/{username}]`, `[Nginx]`, `[SSL]`

## Architecture

### Core Models
- **`UserInfo` dataclass**: group, username, workspace (`{group}/{username}`), label
- **`SandboxInstance` dataclass**: user, port, sandbox, endpoint, url_path (`/{port}/`),
  upstream_host/port/path, password (if secure), cert/key paths

### Key Classes
- **`NginxConfigGenerator`**: generates a **single combined** nginx config with all location
  blocks (one per port), manages sites-available/enabled symlinks, reloads nginx.
  - `generate_combined_config(instances, server_name)` — writes one file with all `/{port}/` locations
- **`SSLCertificateGenerator`**: generates self-signed certs via **openssl CLI** (no pip deps).
  - `generate_cert_for_port(port, server_ip)` — cert named `port-{port}.crt`
  - Embeds server IP in SAN to fix Service Worker SSL errors.

### Groups YAML

```yaml
groups:
  alpha:
    users:
      - alice
      - bob
  beta:
    users:
      - dave
```

Each user gets: sandbox instance → workspace at `/workspace/{group}/{username}` → URL at `https://{server_ip}/{port}/`

### Network Modes (must match server's `docker.network_mode`)

| Mode | Server Endpoint Format | Nginx proxy_pass |
|------|----------------------|------------------|
| **Host** | `{ip}:{port}` | `http://127.0.0.1:{port}/` |
| **Bridge** | `{ip}:{mapped_port}/proxy/{port}` | `http://127.0.0.1:{mapped_port}/proxy/{port}` |

The `--mode` flag must match the server's `[docker]` `network_mode` in `~/.sandbox.toml`:
- `--mode host` when `network_mode = "host"` (default)
- `--mode bridge` when `network_mode = "bridge"`

### Security Modes

| Flag | code-server auth | Password |
|------|-----------------|----------|
| (default) | `--auth none` | None |
| `--secure` | `--auth password` | Auto-generated per-user (24-char token) |

### Certificate Flow (openssl, no cryptography library)

1. On instance creation, `SSLCertificateGenerator` calls `openssl req -x509` via subprocess
2. Config file is generated inline with SAN entries (IP + DNS names)
3. Cert saved to `{ssl_dir}/port-{port}.crt`
4. Nginx config references the first cert for SSL termination (all instances share port 443)
5. code-server always runs **HTTP** inside containers; nginx terminates SSL externally

### Nginx Template Features
- Single server block listening on 80 + 443 ssl
- One `location /{port}/` block per instance
- TLSv1.2 + TLSv1.3, `HIGH:!aNULL:!MD5` ciphers
- WebSocket upgrade headers (`Upgrade`, `Connection "upgrade"`)
- `X-Forwarded-For`, `X-Forwarded-Proto https`, `proxy_redirect off`
- `add_header Service-Worker-Allowed /;` (fixes SW scope errors)
- `proxy_ssl_verify off;` (backend is HTTP)
- `proxy_read/send_timeout 86400` (24h for long-lived WS connections)
- `proxy_buffering off; proxy_request_buffering off;` (real-time data)

## Guardrails

### Must Always
- Generate SSL certs on the **host** via openssl, never inside containers
- Clean up nginx configs + kill sandboxes in `finally` blocks
- Use non-root `vscode` user in containers
- Include Apache 2.0 header on every new file
- Pass `--server-ip` when accessing via IP address (prevents SW SSL errors)
- Match `--mode` to the server's `docker.network_mode` config

### Must Never
- Commit secrets, API keys, or `.key` files to the repository
- Generate certs inside sandbox containers
- Mix unrelated changes in one PR
- Use the `cryptography` pip package (use openssl subprocess instead)
- Mismatch `--mode` flag with server network mode (causes broken proxy_pass)

### Known Gotchas

**Service Worker SSL Error**:
```
SecurityError: Failed to register a ServiceWorker for scope ('https://{ip}/{path}/.../pre/')
An SSL certificate error occurred when fetching the script.
```
- **Root cause**: SW script fetch fails because the cert doesn't cover the target IP/domain
- **Fix**: Pass `--server-ip <IP>` so the cert includes `IP:<ip>` in SAN extensions.

**Network mode mismatch**: If `--mode host` but server runs `network_mode = "bridge"`,
the endpoint URL contains a mapped port + `/proxy/` path. The nginx config will proxy to
the wrong upstream. Always match `--mode` to the server config.

**Environment Variables**:
- `SANDBOX_DOMAIN` — server address (default: `localhost:8080`)
- `SANDBOX_API_KEY` — optional API key
- `SANDBOX_IMAGE` — Docker image (default: `opensandbox/vscode:latest`)
- `PYTHON_VERSION` — Python version in sandbox (default: `3.11`)
- `SSL_DIR` — override default `/etc/nginx/ssl`

## File Map

| File | Purpose |
|------|---------|
| `main.py` | Entry point; argparse CLI; groups loading; instance orchestration |
| `groups.yaml` | Groups and users configuration |
| `setup.sh` | One-time install: python3, nginx, docker.io, docker-buildx, openssl, uv |
| `nginx_config.py` | `NginxConfigGenerator`; combined config with port-based location blocks |
| `ssl_cert.py` | `SSLCertificateGenerator`; openssl-based cert generation (no pip deps) |
| `generate-certs.py` | Legacy mkcert helper (preserved for local dev with browser-trusted certs) |
| `Dockerfile` | Sandbox image: python:3.12-slim + code-server + non-root vscode user |
| `template.portnumber.available.md` | Nginx template reference showing port-based location blocks |
| `../vscode/main.py` | Reference template: single-instance, minimal |
