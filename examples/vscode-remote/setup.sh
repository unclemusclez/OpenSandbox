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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSL_DIR="${SSL_DIR:-/etc/nginx/ssl}"

echo "[Setup] Installing prerequisites for VS Code Remote hackathon environment..."

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

echo "[Setup] Creating SSL directory at ${SSL_DIR}..."
sudo mkdir -p "${SSL_DIR}"
sudo chown -R "$(whoami)":"$(whoami)" "${SSL_DIR}" 2>/dev/null || true

echo "[Setup] Creating nginx sites directories..."
sudo mkdir -p /etc/nginx/sites-available
sudo mkdir -p /etc/nginx/sites-enabled
sudo chown -R "$(whoami)":"$(whoami)" /etc/nginx/sites-available 2>/dev/null || true
sudo chown -R "$(whoami)":"$(whoami)" /etc/nginx/sites-enabled 2>/dev/null || true

# Ensure sites-enabled is included in nginx.conf
if ! grep -q "sites-enabled" /etc/nginx/nginx.conf 2>/dev/null; then
    echo "[Setup] Adding sites-enabled include to nginx.conf..."
    sudo sed -i '/http {/a \\tinclude /etc/nginx/sites-enabled/*;' /etc/nginx/nginx.conf
fi

# Remove default site to avoid default_server conflict
sudo rm -f /etc/nginx/sites-enabled/default

echo "[Setup] Installing mkcert CA..."
sudo mkcert -install 2>/dev/null || mkcert -install 2>/dev/null || {
    echo "[Setup] Warning: mkcert CA install failed (may need sudo)"
}

CAROOT=$(mkcert -caroot 2>/dev/null || true)

echo "[Setup] Working from source..."
#
#git clone https://github.com/unclemusclez/OpenSandbox.git
cd ~/OpenSandbox/examples/vscode
docker build -t opensandbox/vscode:latest .
python -m venv ~/.venv
. ~/.venv/bin/activate
cd ~/OpenSandbox/server
pip install .
cp opensandbox_server/examples/example.config.toml ~/.sandbox.toml
cd ~/OpenSandbox/cli
pip install .

echo "[Setup] Prerequisites installed successfully."
echo "[Setup] SSL certs will be generated at: ${SSL_DIR}"
echo ""
echo "[Setup] Next steps:"
echo "  1. Start the server:  opensandbox-server"
echo "  2. In another terminal, run:"
echo "     python ${SCRIPT_DIR}/main.py --groups ${SCRIPT_DIR}/groups.yaml --external-ip <YOUR_IP>"
if [ -n "$CAROOT" ]; then
    echo ""
    echo "[Setup] For client browsers: install the mkcert CA root from:"
    echo "  ${CAROOT}/rootCA.pem"
fi
