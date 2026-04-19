#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

MODEL="${OLLAMA_MODEL:-}"

if [[ -z "${MODEL}" && -f "${ENV_FILE}" ]]; then
  MODEL="$(awk -F= '/^OLLAMA_MODEL=/{print $2}' "${ENV_FILE}" | tail -n 1 | tr -d '"' | tr -d "'")"
fi

MODEL="${MODEL:-llama3.2:3b}"

echo "Pulling Ollama model: ${MODEL}"
docker exec polymarket-ollama ollama pull "${MODEL}"
