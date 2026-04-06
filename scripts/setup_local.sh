#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MINIMIND_DIR="${ROOT_DIR}/../minimind"
VENV_DIR="${ROOT_DIR}/.venv"
MODEL_DIR_DEFAULT="${ROOT_DIR}/../minimind-3"
MODEL_DIR="${1:-$MODEL_DIR_DEFAULT}"

echo "[setup] project: ${ROOT_DIR}"
echo "[setup] minimind: ${MINIMIND_DIR}"
echo "[setup] venv: ${VENV_DIR}"

if [[ ! -d "${MINIMIND_DIR}" ]]; then
  echo "[error] minimind repo not found at ${MINIMIND_DIR}"
  exit 1
fi

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

echo "[setup] installing micro-local-claude dependencies..."
pip install -r "${ROOT_DIR}/requirements.txt"

echo "[setup] installing minimind dependencies..."
# --no-compile avoids bytecode compile failures on restricted environments.
pip install --no-compile -r "${MINIMIND_DIR}/requirements.txt"
pip install fastapi uvicorn

if [[ ! -f "${MODEL_DIR}/config.json" ]]; then
  echo "[setup] model not found at ${MODEL_DIR}"
  echo "[setup] downloading minimind-3 from HuggingFace..."
  HF_HOME="${ROOT_DIR}/.hf" HUGGINGFACE_HUB_CACHE="${ROOT_DIR}/.hf/hub" \
  python - <<PY
from huggingface_hub import snapshot_download
snapshot_download(repo_id="jingyaogong/minimind-3", local_dir=r"${MODEL_DIR}")
print("downloaded:", r"${MODEL_DIR}")
PY
fi

cat <<EOF

[done] setup complete.

Start interactive mode:
  source "${VENV_DIR}/bin/activate"
  python -m micro_local_claude --model-path "${MODEL_DIR}"

EOF

