#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

services=(ollama searxng lightpanda postgres redis)

if [[ "${1:-}" == "--core" ]]; then
  services=(ollama searxng)
fi

echo "Starting services: ${services[*]}"
cd "${REPO_ROOT}"
docker compose up -d "${services[@]}"

"${SCRIPT_DIR}/wait_for_services.sh" "${services[@]}"

if printf '%s\n' "${services[@]}" | grep -qx "ollama"; then
  "${SCRIPT_DIR}/pull_ollama_model.sh"
fi

echo
echo "Stack is ready."
docker compose ps
