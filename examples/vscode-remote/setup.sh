#!/usr/bin/env bash
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

set -euo pipefail

SSL_DIR="${SSL_DIR:-/etc/nginx/ssl}"

echo "[Setup] Installing prerequisites for VS Code Remote..."
echo ""

# ── System packages ──────────────────────────────────────────────────
echo "[Setup] Installing system packages..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    python-is-python3 \
    nginx \
    mkcert \
    docker.io \
    docker-buildx \
    openssl \
    ca-certificates \
    curl \
    libnss3-tools

# ── uv ───────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "[Setup] Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "[Setup] uv: $(uv --version)"

# ── mkcert CA ────────────────────────────────────────────────────────
echo "[Setup] Installing mkcert CA..."
sudo mkcert -install 2>/dev/null || mkcert -install 2>/dev/null || {
    echo "[Setup] Warning: mkcert CA install failed"
    echo "[Setup] You may need to run: sudo mkcert -install"
}

CAROOT=$(mkcert -caroot 2>/dev/null || true)
if [ -n "$CAROOT" ]; then
    echo "[Setup] mkcert CA root: ${CAROOT}"
    echo "[Setup] Copy rootCA.pem to client machines for browser trust"
fi

# ── SSL directory ────────────────────────────────────────────────────
echo "[Setup] Creating SSL directory at ${SSL_DIR}..."
sudo mkdir -p "${SSL_DIR}"
sudo chown -R "$(whoami)":"$(whoami)" "${SSL_DIR}" 2>/dev/null || true

# ── Nginx directories ────────────────────────────────────────────────
echo "[Setup] Configuring nginx..."
sudo mkdir -p /etc/nginx/sites-available
sudo mkdir -p /etc/nginx/sites-enabled

# Ensure sites-enabled is included in nginx.conf
if ! grep -q "sites-enabled" /etc/nginx/nginx.conf 2>/dev/null; then
    echo "[Setup] Adding sites-enabled include to nginx.conf..."
    sudo sed -i '/http {/a \\tinclude /etc/nginx/sites-enabled/*;' /etc/nginx/nginx.conf
fi

# Remove default site to avoid default_server conflict
sudo rm -f /etc/nginx/sites-enabled/default

# ── Docker image ─────────────────────────────────────────────────────
echo "[Setup] Building VS Code Docker image..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if docker image inspect opensandbox/vscode:latest &>/dev/null; then
    echo "[Setup] Docker image opensandbox/vscode:latest already exists"
else
    docker build -t opensandbox/vscode:latest "${SCRIPT_DIR}"
fi

# ── OpenSandbox server ───────────────────────────────────────────────
echo "[Setup] Setting up OpenSandbox server..."
if ! command -v opensandbox-server &>/dev/null; then
    uv pip install opensandbox-server
fi

if [ ! -f ~/.sandbox.toml ]; then
    echo "[Setup] Creating default server config at ~/.sandbox.toml..."
    opensandbox-server init-config ~/.sandbox.toml --example docker
fi

# ── Done ─────────────────────────────────────────────────────────────
echo ""
echo "[Setup] Prerequisites installed successfully."
echo ""
echo "[Setup] Next steps:"
echo "  1. Start the server:  opensandbox-server"
echo "  2. In another terminal, run:"
echo "     uv run python ${SCRIPT_DIR}/main.py --groups ${SCRIPT_DIR}/groups.yaml --external-ip <YOUR_IP>"
echo ""
echo "[Setup] For client browsers: install the mkcert CA root from:"
echo "  ${CAROOT}/rootCA.pem"
