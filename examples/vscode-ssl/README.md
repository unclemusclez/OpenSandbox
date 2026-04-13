# VS Code SSL Example

Single-instance VS Code sandbox with built-in code-server SSL support. No nginx or external reverse proxy required.

## How It Works

1. Creates a sandbox from the `opensandbox/vscode-ssl` image (includes openssl)
2. Generates a self-signed certificate inside the sandbox using `openssl req -x509`
3. Starts code-server with `--cert` and `--cert-key` flags for native HTTPS
4. Browser connects directly to code-server over HTTPS

## Build the Docker Image

```shell
cd examples/vscode-ssl
docker build -t opensandbox/vscode-ssl:latest .
```

The image includes:
- code-server (VS Code Web) pre-installed
- openssl for self-signed certificate generation
- Non-root user (vscode) for security
- `/certs` directory for SSL certificates
- Workspace directory at `/workspace`

## Start OpenSandbox Server

```shell
pip install opensandbox-server
opensandbox-server init-config ~/.sandbox.toml --example docker
opensandbox-server
```

## Run

```shell
# Default (self-signed cert, HTTPS on port 8443)
pip install opensandbox
python examples/vscode-ssl/main.py

# With password authentication
python examples/vscode-ssl/main.py --secure

# Auto-detect external IP for certificate SAN
python examples/vscode-ssl/main.py --external-ip 1.2.3.4

# Custom code-server port
python examples/vscode-ssl/main.py --port 9443

# Custom timeout (minutes)
python examples/vscode-ssl/main.py --timeout 30
```

## SSL Certificate Details

- **Self-signed**: Generated inside the sandbox at runtime using `openssl req -x509`
- **SAN entries**: Always includes `DNS:localhost` and `IP:127.0.0.1`. Use `--external-ip` to add your public IP
- **Browser warning**: Self-signed certs trigger browser security warnings — accept to proceed
- **No nginx**: code-server handles HTTPS natively — no reverse proxy needed

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SANDBOX_DOMAIN` | Server address | `localhost:8080` |
| `SANDBOX_API_KEY` | Optional API key | None |
| `SANDBOX_IMAGE` | Docker image | `opensandbox/vscode-ssl:latest` |
| `PYTHON_VERSION` | Python version in sandbox | `3.11` |

## Comparison with Other VS Code Examples

| Feature | `vscode` | `vscode-ssl` | `vscode-remote` |
|---------|----------|-------------|-----------------|
| Instances | Single | Single | Multiple (groups) |
| HTTPS | No | Yes (code-server native) | Yes (nginx reverse proxy) |
| SSL cert | N/A | Self-signed (openssl) | mkcert/openssl on host |
| Reverse proxy | No | No | nginx |
| External deps | None | None | nginx, mkcert |

## References

- [code-server HTTPS docs](https://coder.com/docs/code-server/latest/guide#https-and-self-signed-certificates)
- [code-server (VS Code Web)](https://github.com/coder/code-server)
