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
    docker.io \
    docker-buildx \
    openssl \
    ca-certificates \
    curl

echo "[Setup] Creating SSL directory at ${SSL_DIR}..."
sudo mkdir -p "${SSL_DIR}"
sudo chown -R "$(whoami)":"$(whoami)" "${SSL_DIR}" 2>/dev/null || true

echo "[Setup] Creating nginx sites directories..."
sudo mkdir -p /etc/nginx/sites-available
sudo mkdir -p /etc/nginx/sites-enabled
sudo chown -R "$(whoami)":"$(whoami)" /etc/nginx/sites-available 2>/dev/null || true
sudo chown -R "$(whoami)":"$(whoami)" /etc/nginx/sites-enabled 2>/dev/null || true


> If you prefer working from source, you can still clone the repo for development, but you no longer need to clone this repository just to start the server.
> You'll also require an instance of docker running.
> ```bash
git clone https://github.com/unclemusclez/OpenSandbox.git
python -m venv ~/.venv
. ~/.venv/bin/activate
cd ~/OpenSandbox/server
pip install .
cp opensandbox_server/examples/example.config.toml ~/.sandbox.toml
cd ~/OpenSandbox/cli
pip install .
#python -m opensandbox_server.main need a new script for server run.
```

echo "[Setup] Prerequisites installed successfully."
echo "[Setup] SSL certs will be generated at: ${SSL_DIR}"
echo "[Setup] To run: cd ${SCRIPT_DIR} && uv run python main.py --instances 1 --use-nginx"
