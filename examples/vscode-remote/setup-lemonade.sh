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

PORT="${LEMONADE_PORT:-13305}"
HOST="${LEMONADE_HOST:-0.0.0.0}"
BACKEND="${LEMONADE_BACKEND:-rocm}"
CTX_SIZE="${LEMONADE_CTX_SIZE:-4096}"
MODEL="${LEMONADE_MODEL:-Gemma-3-4b-it-GGUF}"
EXTERNAL_IP="${LEMONADE_EXTERNAL_IP:-}"
GENERATE_KEYS="${LEMONADE_GENERATE_KEYS:-false}"
KILO_CONFIG_OUTPUT="${1:-${SCRIPT_DIR}/kilo.json}"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install, configure, and start the Lemonade inference server as a systemd
service.  Generates a kilo.json for Kilo Code so sandbox VS Code instances
can connect to the local LLM endpoint.

Options:
  --port PORT           Server port (default: ${PORT})
  --host HOST           Bind address (default: ${HOST})
  --backend BACKEND     llama.cpp backend: auto, rocm, vulkan, cpu (default: ${BACKEND})
  --ctx-size SIZE       Default context size (default: ${CTX_SIZE})
  --model MODEL         Model to pull and load (default: ${MODEL})
  --external-ip IP      External IP for kilo.json base URL
  --generate-keys       Generate API key and admin key in systemd override
  --kilo-config PATH    Output path for kilo.json (default: ${KILO_CONFIG_OUTPUT})
  -h, --help            Show this help

Environment variables (override defaults):
  LEMONADE_PORT, LEMONADE_HOST, LEMONADE_BACKEND, LEMONADE_CTX_SIZE,
  LEMONADE_MODEL, LEMONADE_EXTERNAL_IP, LEMONADE_GENERATE_KEYS

Examples:
  # Full setup with API keys and external IP
  $(basename "$0") --generate-keys --external-ip 1.2.3.4

  # Custom model and port
  $(basename "$0") --model Qwen2.5-Coder-7B-Instruct-GGUF --port 9000

  # Quick default setup (no auth, localhost only)
  $(basename "$0")
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)         PORT="$2"; shift 2 ;;
        --host)         HOST="$2"; shift 2 ;;
        --backend)      BACKEND="$2"; shift 2 ;;
        --ctx-size)     CTX_SIZE="$2"; shift 2 ;;
        --model)        MODEL="$2"; shift 2 ;;
        --external-ip)  EXTERNAL_IP="$2"; shift 2 ;;
        --generate-keys) GENERATE_KEYS="true"; shift ;;
        --kilo-config)  KILO_CONFIG_OUTPUT="$2"; shift 2 ;;
        -h|--help)      usage; exit 0 ;;
        *)              echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

echo "[Lemonade] Installing lemonade-server via PPA..."
sudo add-apt-repository -y ppa:lemonade-team/stable
sudo apt-get update
sudo apt-get install -y lemonade-server
sudo update-pciids 2>/dev/null || true

echo "[Lemonade] Configuring server..."
lemonade config set port="${PORT}" host="${HOST}" llamacpp.backend="${BACKEND}" ctx_size="${CTX_SIZE}"

API_KEY=""
ADMIN_KEY=""

if [[ "${GENERATE_KEYS}" == "true" ]]; then
    API_KEY="$(openssl rand -base64 32 | tr -d '/+=\n' | head -c 32)"
    ADMIN_KEY="$(openssl rand -base64 32 | tr -d '/+=\n' | head -c 32)"

    OVERRIDE_DIR="/etc/systemd/system/lemonade-server.service.d"
    sudo mkdir -p "${OVERRIDE_DIR}"
    sudo tee "${OVERRIDE_DIR}/override.conf" > /dev/null <<EOF
[Service]
Environment="LEMONADE_API_KEY=${API_KEY}"
Environment="LEMONADE_ADMIN_API_KEY=${ADMIN_KEY}"
EOF
    sudo systemctl daemon-reload

    echo "[Lemonade] API keys configured in systemd override"
    echo "[Lemonade]   API Key:       ${API_KEY}"
    echo "[Lemonade]   Admin API Key: ${ADMIN_KEY}"
fi

echo "[Lemonade] Restarting service..."
sudo systemctl restart lemonade-server

echo "[Lemonade] Waiting for server to be ready..."
sleep 3

if sudo systemctl is-active --quiet lemonade-server; then
    echo "[Lemonade] Server is running"
else
    echo "[Lemonade] Error: Server failed to start"
    sudo systemctl status lemonade-server --no-pager || true
    exit 1
fi

echo "[Lemonade] Pulling model: ${MODEL}"
lemonade pull "${MODEL}"

echo "[Lemonade] Loading model via API..."
AUTH_HEADER=""
if [[ -n "${ADMIN_KEY}" ]]; then
    AUTH_HEADER="-H \"Authorization: Bearer ${ADMIN_KEY}\""
elif [[ -n "${API_KEY}" ]]; then
    AUTH_HEADER="-H \"Authorization: Bearer ${API_KEY}\""
fi

LOCAL_HOST="localhost"
if [[ "${HOST}" != "0.0.0.0" ]]; then
    LOCAL_HOST="${HOST}"
fi

eval curl -sf -X POST "http://${LOCAL_HOST}:${PORT}/api/v1/load" \
    -H "Content-Type: application/json" ${AUTH_HEADER} \
    -d "{\"model\": \"${MODEL}\"}" && echo "[Lemonade] Model loaded: ${MODEL}" || \
    echo "[Lemonade] Warning: Model load request failed (model may still be loading)"

# Resolve base URL for sandbox containers: external_ip > docker gateway > localhost
if [[ -n "${EXTERNAL_IP}" ]]; then
    BASE_HOST="${EXTERNAL_IP}"
else
    DOCKER_GW="$(docker network inspect bridge -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null || true)"
    if [[ -n "${DOCKER_GW}" ]]; then
        BASE_HOST="${DOCKER_GW}"
    else
        BASE_HOST="localhost"
    fi
fi

BASE_URL="http://${BASE_HOST}:${PORT}/v1"
AUTH_VAL="${ADMIN_KEY:-${API_KEY:-none}}"
MODEL_ID="$(echo "${MODEL}" | tr '[:upper:]' '[:lower:]' | tr '.' '-')"

echo "[Lemonade] Generating kilo.json at ${KILO_CONFIG_OUTPUT}"
mkdir -p "$(dirname "${KILO_CONFIG_OUTPUT}")"
cat > "${KILO_CONFIG_OUTPUT}" <<EOF
{
  "provider": {
    "lemonade": {
      "models": {
        "${MODEL_ID}": {
          "name": "${MODEL}",
          "limit": {
            "context": ${CTX_SIZE},
            "output": 4096
          }
        }
      },
      "options": {
        "apiKey": "${AUTH_VAL}",
        "baseURL": "${BASE_URL}"
      }
    }
  },
  "model": "lemonade/${MODEL_ID}"
}
EOF

echo ""
echo "========================================================================"
echo "Lemonade Inference Server"
echo "========================================================================"
echo "  Local endpoint: http://${LOCAL_HOST}:${PORT}"
echo "  OpenAI API:     http://${LOCAL_HOST}:${PORT}/v1/"
if [[ -n "${EXTERNAL_IP}" ]]; then
    echo "  External API:   http://${EXTERNAL_IP}:${PORT}/v1/"
fi
echo "  Model:          ${MODEL}"
if [[ -n "${API_KEY}" ]]; then
    echo "  API Key:        ${API_KEY}"
fi
if [[ -n "${ADMIN_KEY}" ]]; then
    echo "  Admin API Key:  ${ADMIN_KEY}"
fi
echo ""
echo "  Kilo Code config: ${KILO_CONFIG_OUTPUT}"
echo "  Base URL:  ${BASE_URL}"
echo "  API Key:   ${AUTH_VAL}"
echo "  Model:     lemonade/${MODEL_ID}"
echo ""
echo "  Service manages its own lifecycle (systemd)."
echo "  Status:   sudo systemctl status lemonade-server"
echo "  Stop:     sudo systemctl stop lemonade-server"
echo "  Restart:  sudo systemctl restart lemonade-server"
echo "  Logs:     sudo journalctl -u lemonade-server -f"
echo ""
echo "  To use with VS Code sandboxes:"
echo "    python ${SCRIPT_DIR}/main.py --groups groups.yaml --external-ip ${EXTERNAL_IP:-<IP>} --lemonade ${KILO_CONFIG_OUTPUT}"
