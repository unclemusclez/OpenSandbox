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

echo "[Lemonade] Installing lemonade-server via PPA..."

sudo add-apt-repository -y ppa:lemonade-team/stable
sudo apt-get update
sudo apt-get install -y lemonade-server

echo "[Lemonade] Updating PCI IDs for GPU detection..."
sudo update-pciids 2>/dev/null || true

echo "[Lemonade] Installation complete."
echo ""
echo "[Lemonade] Next steps:"
echo "  1. Configure and start the server:"
echo "     python ${SCRIPT_DIR}/lemonade_server.py run --model Gemma-3-4b-it-GGUF --generate-keys --external-ip <YOUR_IP>"
echo ""
echo "  2. Or configure manually:"
echo "     python ${SCRIPT_DIR}/lemonade_server.py configure --generate-keys"
echo "     python ${SCRIPT_DIR}/lemonade_server.py start"
echo "     python ${SCRIPT_DIR}/lemonade_server.py pull --model Gemma-3-4b-it-GGUF"
