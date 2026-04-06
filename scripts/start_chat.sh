#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
MINIMIND_DIR="${ROOT_DIR}/../minimind"
MODEL_DIR="${ROOT_DIR}/models/minimind-3"
HF_HOME_DIR="${ROOT_DIR}/.hf"

required_files=(
  "config.json"
  "generation_config.json"
  "model.safetensors"
  "special_tokens_map.json"
  "tokenizer.json"
  "tokenizer_config.json"
  "chat_template.jinja"
)

if [[ ! -d "${MINIMIND_DIR}" ]]; then
  echo "[error] minimind repo not found: ${MINIMIND_DIR}"
  echo "[hint] this project expects sibling repositories under the same parent directory."
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi
source "${VENV_DIR}/bin/activate"

if ! python - <<'PY' >/dev/null 2>&1
import openai, torch, transformers, fastapi, uvicorn  # noqa: F401
PY
then
  echo "[setup] installing dependencies, this may take a while..."
  pip install -r "${ROOT_DIR}/requirements.txt"
  pip install --no-compile -r "${MINIMIND_DIR}/requirements.txt"
  pip install fastapi uvicorn
fi

missing=0
for file in "${required_files[@]}"; do
  if [[ ! -f "${MODEL_DIR}/${file}" ]]; then
    missing=1
    break
  fi
done

if [[ "${missing}" -eq 1 ]]; then
  echo "[setup] minimind-3 not found locally, downloading once..."
  mkdir -p "${MODEL_DIR}" "${HF_HOME_DIR}"
  HF_HOME="${HF_HOME_DIR}" HUGGINGFACE_HUB_CACHE="${HF_HOME_DIR}/hub" \
  python - <<PY
from huggingface_hub import snapshot_download
snapshot_download(repo_id="jingyaogong/minimind-3", local_dir=r"${MODEL_DIR}")
print("downloaded:", r"${MODEL_DIR}")
PY
fi

echo "[run] starting local chat with local minimind-3 model..."
exec python -m micro_local_claude --model-path "${MODEL_DIR}" "$@"

