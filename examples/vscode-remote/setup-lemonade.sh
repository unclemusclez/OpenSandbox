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
CTX_SIZE="${LEMONADE_CTX_SIZE:-262144}"
MODEL="${LEMONADE_MODEL:-unsloth/gemma-4-31B-it-GGUF:Q8_K_XL}"
MODEL_NAME="${LEMONADE_MODEL_NAME:-gemma-4-31b-it}"
EXTERNAL_IP="${LEMONADE_EXTERNAL_IP:-}"
GENERATE_KEYS="${LEMONADE_GENERATE_KEYS:-false}"
KILO_CONFIG_OUTPUT="${LEMONADE_KILO_CONFIG:-${SCRIPT_DIR}/kilo.json}"
GROUPS_FILE=""
GROUP_FILTER=""
NUM_USERS="${LEMONADE_NUM_USERS:-1}"
PER_USER_CTX=262144
CONFIG_DIR="/var/lib/lemonade/.cache/lemonade"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install, configure, and start the Lemonade inference server as a systemd
service.  Generates user_models.json, recipe_options.json, and kilo.json
for Kilo Code so sandbox VS Code instances can connect to the local LLM.

The --groups flag reads a groups.yaml to determine the number of parallel
users, which scales the llama.cpp context size and parallel slots.

Options:
  --groups FILE         Path to groups.yaml; user count scales ctx-size and -np
  --group GROUP         Filter to a single group from groups.yaml
  --num-users N         Override number of parallel users (default: 1, or auto from --groups)
  --port PORT           Server port (default: ${PORT})
  --host HOST           Bind address (default: ${HOST})
  --backend BACKEND     llama.cpp backend: auto, rocm, vulkan, cpu (default: ${BACKEND})
  --ctx-size SIZE       Per-user context size (default: ${CTX_SIZE})
  --model MODEL         HuggingFace checkpoint (default: ${MODEL})
  --model-name NAME     Short model name for user_models.json (default: ${MODEL_NAME})
  --external-ip IP      External IP for kilo.json base URL
  --generate-keys       Generate API key and admin key in systemd override
  --kilo-config PATH    Output path for kilo.json (default: ${KILO_CONFIG_OUTPUT})
  -h, --help            Show this help

Environment variables (override defaults):
  LEMONADE_PORT, LEMONADE_HOST, LEMONADE_BACKEND, LEMONADE_CTX_SIZE,
  LEMONADE_MODEL, LEMONADE_MODEL_NAME, LEMONADE_EXTERNAL_IP,
  LEMONADE_GENERATE_KEYS, LEMONADE_NUM_USERS, LEMONADE_KILO_CONFIG

Examples:
  # Full setup with groups.yaml for user count
  $(basename "$0") --groups groups.yaml --generate-keys --external-ip 1.2.3.4

  # Single group with API keys
  $(basename "$0") --groups groups.yaml --group alpha --generate-keys --external-ip 1.2.3.4

  # Override user count directly
  $(basename "$0") --num-users 8 --generate-keys --external-ip 1.2.3.4
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --groups)        GROUPS_FILE="$2"; shift 2 ;;
        --group)         GROUP_FILTER="$2"; shift 2 ;;
        --num-users)     NUM_USERS="$2"; shift 2 ;;
        --port)          PORT="$2"; shift 2 ;;
        --host)          HOST="$2"; shift 2 ;;
        --backend)       BACKEND="$2"; shift 2 ;;
        --ctx-size)      CTX_SIZE="$2"; shift 2 ;;
        --model)         MODEL="$2"; shift 2 ;;
        --model-name)    MODEL_NAME="$2"; shift 2 ;;
        --external-ip)   EXTERNAL_IP="$2"; shift 2 ;;
        --generate-keys) GENERATE_KEYS="true"; shift ;;
        --kilo-config)   KILO_CONFIG_OUTPUT="$2"; shift 2 ;;
        -h|--help)       usage; exit 0 ;;
        *)               echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

# Resolve num_users from groups.yaml
if [[ -n "${GROUPS_FILE}" ]]; then
    if command -v python3 &>/dev/null; then
        if [[ -n "${GROUP_FILTER}" ]]; then
            NUM_USERS="$(python3 -c "
import yaml, sys
with open('${GROUPS_FILE}') as f:
    data = yaml.safe_load(f)
groups = data.get('groups', {})
count = sum(len(g.get('users', [])) for n, g in groups.items() if n == '${GROUP_FILTER}')
print(count)
")"
        else
            NUM_USERS="$(python3 -c "
import yaml
with open('${GROUPS_FILE}') as f:
    data = yaml.safe_load(f)
groups = data.get('groups', {})
print(sum(len(g.get('users', [])) for g in groups.values()))
")"
        fi
        echo "[Lemonade] ${NUM_USERS} user(s) from ${GROUPS_FILE}"
    else
        echo "[Lemonade] Warning: python3 not available, using --num-users=${NUM_USERS}"
    fi
fi

if [[ "${NUM_USERS}" -lt 1 ]]; then
    NUM_USERS=1
fi

TOTAL_CTX=$((PER_USER_CTX * NUM_USERS))

echo "[Lemonade] Installing lemonade-server via PPA..."
sudo add-apt-repository -y ppa:lemonade-team/stable
sudo apt-get update
sudo apt-get install -y lemonade-server
sudo update-pciids 2>/dev/null || true

echo "[Lemonade] Stopping server for direct config..."
sudo systemctl stop lemonade-server 2>/dev/null || true

echo "[Lemonade] Configuring server..."
CONFIG_TMP="$(mktemp)"
if sudo test -f "${CONFIG_DIR}/config.json"; then
    sudo cat "${CONFIG_DIR}/config.json" > "${CONFIG_TMP}"
else
    echo '{}' > "${CONFIG_TMP}"
fi
python3 <<'PYEOF' "${CONFIG_TMP}" "${PORT}" "${HOST}" "${BACKEND}" "${CTX_SIZE}"
import json, sys
path, port, host, backend, ctx_size = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5])
with open(path) as f:
    existing = json.load(f)
existing.update({
    "port": port,
    "host": host,
    "ctx_size": ctx_size,
})
llamacpp = existing.setdefault("llamacpp", {})
llamacpp["backend"] = backend
with open(path, "w") as f:
    json.dump(existing, f, indent=2)
PYEOF
sudo cp "${CONFIG_TMP}" "${CONFIG_DIR}/config.json"
rm -f "${CONFIG_TMP}"
echo "[Lemonade] Configuration written to ${CONFIG_DIR}/config.json"

echo "[Lemonade] Writing user_models.json..."
sudo mkdir -p "${CONFIG_DIR}"
USER_MODELS="${CONFIG_DIR}/user_models.json"
USER_MODELS_TMP="$(mktemp)"
if sudo test -f "${USER_MODELS}"; then
    sudo cat "${USER_MODELS}" > "${USER_MODELS_TMP}"
else
    echo '{}' > "${USER_MODELS_TMP}"
fi
python3 <<'PYEOF' "${USER_MODELS_TMP}" "${MODEL_NAME}" "${MODEL}"
import json, sys
path, model_name, checkpoint = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    existing = json.load(f)
existing[model_name] = {"checkpoint": checkpoint, "recipe": "llamacpp", "size": 31.0}
with open(path, "w") as f:
    json.dump(existing, f, indent=2)
PYEOF
sudo cp "${USER_MODELS_TMP}" "${USER_MODELS}"
rm -f "${USER_MODELS_TMP}"
echo "[Lemonade] user_models.json updated with ${MODEL_NAME}"

echo "[Lemonade] Writing recipe_options.json..."
RECIPE_OPTIONS="${CONFIG_DIR}/recipe_options.json"
RECIPE_OPTIONS_TMP="$(mktemp)"
if sudo test -f "${RECIPE_OPTIONS}"; then
    sudo cat "${RECIPE_OPTIONS}" > "${RECIPE_OPTIONS_TMP}"
else
    echo '{}' > "${RECIPE_OPTIONS_TMP}"
fi
PREFIXED_NAME="user.${MODEL_NAME}"
LLAMACPP_ARGS="-ngl 999 -b 8192 -ub 8192 -to 3600 -ctk q8_0 -ctv q8_0 --jinja --ctx-size ${TOTAL_CTX} --temp 1.0 --top-k 64 --top-p 0.95 --min-p 0.0 --repeat-penalty 1.0 --no-webui --threads-http -1 --threads -1 -np ${NUM_USERS}"
python3 <<'PYEOF' "${RECIPE_OPTIONS_TMP}" "${PREFIXED_NAME}" "${BACKEND}" "${PER_USER_CTX}" "${LLAMACPP_ARGS}"
import json, sys
path, prefixed_name, backend, ctx_size, llamacpp_args = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
with open(path) as f:
    existing = json.load(f)
existing[prefixed_name] = {
    "ctx_size": ctx_size,
    "llamacpp_backend": backend,
    "llamacpp_args": llamacpp_args,
}
with open(path, "w") as f:
    json.dump(existing, f, indent=2)
PYEOF
sudo cp "${RECIPE_OPTIONS_TMP}" "${RECIPE_OPTIONS}"
rm -f "${RECIPE_OPTIONS_TMP}"
echo "[Lemonade] recipe_options.json updated for ${PREFIXED_NAME}"
echo "[Lemonade]   ctx-size: ${TOTAL_CTX} (${PER_USER_CTX} x ${NUM_USERS} users)"
echo "[Lemonade]   -np: ${NUM_USERS}"

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
    -d "{\"model\": \"${PREFIXED_NAME}\"}" && echo "[Lemonade] Model loaded: ${PREFIXED_NAME}" || \
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

echo "[Lemonade] generating kilo.json at ${KILO_CONFIG_OUTPUT}"
mkdir -p "$(dirname "${KILO_CONFIG_OUTPUT}")"
cat > "${KILO_CONFIG_OUTPUT}" <<EOF
{
  "provider": {
    "lemonade": {
      "models": {
        "${MODEL_NAME}": {
          "name": "${MODEL}",
          "limit": {
            "context": ${PER_USER_CTX},
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
  "model": "lemonade/${MODEL_NAME}"
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
echo "  Model name:     ${PREFIXED_NAME}"
echo "  Parallel users: ${NUM_USERS}"
echo "  Total ctx-size: ${TOTAL_CTX} (${PER_USER_CTX} x ${NUM_USERS})"
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
echo "  Model:     lemonade/${MODEL_NAME}"
echo ""
echo "  Service manages its own lifecycle (systemd)."
echo "  Status:   sudo systemctl status lemonade-server"
echo "  Stop:     sudo systemctl stop lemonade-server"
echo "  Restart:  sudo systemctl restart lemonade-server"
echo "  Logs:     sudo journalctl -u lemonade-server -f"
echo ""
echo "  To use with VS Code sandboxes:"
echo "    python ${SCRIPT_DIR}/main.py --groups groups.yaml --external-ip ${EXTERNAL_IP:-<IP>} --lemonade ${KILO_CONFIG_OUTPUT}"
