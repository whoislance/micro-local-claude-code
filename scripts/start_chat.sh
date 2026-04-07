#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"
MODEL_DIR="${ROOT_DIR}/models/minimind-3"
HF_HOME_DIR="${ROOT_DIR}/.hf"
BOOTSTRAP_DIR="${ROOT_DIR}/.bootstrap"
MICROMAMBA_DIR="${BOOTSTRAP_DIR}/micromamba"
MICROMAMBA_BIN="${MICROMAMBA_DIR}/bin/micromamba"

required_files=(
  "config.json"
  "generation_config.json"
  "model.safetensors"
  "special_tokens_map.json"
  "tokenizer.json"
  "tokenizer_config.json"
  "chat_template.jinja"
)

system_python_supports_runtime() {
  python3 - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
}

venv_supports_runtime() {
  if [[ ! -x "${VENV_PYTHON}" || ! -x "${VENV_PIP}" ]]; then
    return 1
  fi
  "${VENV_PYTHON}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
}

download_micromamba() {
  if [[ -x "${MICROMAMBA_BIN}" ]]; then
    return 0
  fi

  mkdir -p "${MICROMAMBA_DIR}"
  local archive="${BOOTSTRAP_DIR}/micromamba.tar.bz2"
  if command -v curl >/dev/null 2>&1; then
    curl -L "https://micro.mamba.pm/api/micromamba/linux-64/latest" -o "${archive}"
  else
    wget -O "${archive}" "https://micro.mamba.pm/api/micromamba/linux-64/latest"
  fi
  tar -xjf "${archive}" -C "${MICROMAMBA_DIR}" bin/micromamba
  chmod +x "${MICROMAMBA_BIN}"
}

create_micromamba_env() {
  download_micromamba
  rm -rf "${VENV_DIR}"
  MAMBA_ROOT_PREFIX="${BOOTSTRAP_DIR}/micromamba-root" \
  "${MICROMAMBA_BIN}" create -y -p "${VENV_DIR}" -c conda-forge python=3.10 pip
}

create_virtualenv() {
  if venv_supports_runtime; then
    return 0
  fi

  rm -rf "${VENV_DIR}"
  if ! system_python_supports_runtime; then
    echo "[warn] system python is too old for minimind-3 dependencies, bootstrapping Python 3.10..."
    create_micromamba_env
    return 0
  fi

  if python3 -m venv "${VENV_DIR}"; then
    return 0
  fi

  echo "[warn] python3 -m venv failed, trying rootless bootstrap..."
  mkdir -p "${BOOTSTRAP_DIR}"

  if ! python3 -m pip --version >/dev/null 2>&1; then
    local get_pip="${BOOTSTRAP_DIR}/get-pip.py"
    if [[ ! -f "${get_pip}" ]]; then
      python3 - <<PY
from pathlib import Path
from urllib.request import urlretrieve
import sys

major, minor = sys.version_info[:2]
if (major, minor) <= (3, 7):
    url = "https://bootstrap.pypa.io/pip/3.7/get-pip.py"
else:
    url = "https://bootstrap.pypa.io/get-pip.py"
target = Path(r"${get_pip}")
urlretrieve(url, target)
print(target)
PY
    fi
    python3 "${get_pip}" --user
  fi

  python3 -m pip install --user virtualenv
  if python3 -m virtualenv "${VENV_DIR}"; then
    return 0
  fi

  echo "[warn] virtualenv bootstrap failed, bootstrapping Python 3.10..."
  create_micromamba_env
}

create_virtualenv

if ! "${VENV_PYTHON}" - <<'PY' >/dev/null 2>&1
import openai, torch, transformers, fastapi, uvicorn, huggingface_hub  # noqa: F401
PY
then
  echo "[setup] installing dependencies, this may take a while..."
  "${VENV_PIP}" install -r "${ROOT_DIR}/requirements.txt"
  "${VENV_PIP}" install --no-compile torch
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
  "${VENV_PYTHON}" - <<PY
from huggingface_hub import snapshot_download
snapshot_download(repo_id="jingyaogong/minimind-3", local_dir=r"${MODEL_DIR}")
print("downloaded:", r"${MODEL_DIR}")
PY
fi

echo "[run] starting local chat with local minimind-3 model..."
exec "${VENV_PYTHON}" -m micro_local_claude --model-path "${MODEL_DIR}" "$@"
