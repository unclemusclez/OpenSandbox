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

echo "[Setup] Installing prerequisites for VS Code SSL example..."

sudo apt-get update
sudo apt-get upgrade

sudo apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    python-is-python3 \
    docker.io \
    docker-buildx \
    openssl \
    ca-certificates \
    curl

sudo usermod -aG docker $USER
newgrp docker

echo "[Setup] Working from source..."
git clone https://github.com/unclemusclez/OpenSandbox.git
cd ~/OpenSandbox/examples/vscode-ssl
docker build -t opensandbox/vscode-ssl:latest .
python -m venv ~/.venv
. ~/.venv/bin/activate
cd ~/OpenSandbox/server
pip install .
cp opensandbox_server/examples/example.config.toml ~/.sandbox.toml
cd ~/OpenSandbox/cli
pip install .

echo "[Setup] Prerequisites installed successfully."
echo ""
echo "[Setup] Next steps:"
echo "  1. Start the server:  opensandbox-server"
echo "  2. In another terminal, run:"
echo "     . ~/.venv/bin/activate"
echo "     python ${SCRIPT_DIR}/main.py --external-ip <YOUR_IP>"
echo ""
echo "[Setup] Note: SSL certs are generated inside the sandbox (no nginx or host certs needed)."
