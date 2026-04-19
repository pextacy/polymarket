#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STACK_ROOT="${STACK_ROOT:-${REPO_ROOT}/../oss-stack}"
GITHUB_OWNER="${GITHUB_OWNER:-caelum0x}"
USE_FORKS="${USE_FORKS:-1}"

repos=(
  "daytona:daytonaio/daytona:daytona"
  "lightpanda-browser:lightpanda-io/browser:browser"
  "ollama:ollama/ollama:ollama"
  "qdrant:qdrant/qdrant:qdrant"
  "searxng:searxng/searxng:searxng"
  "searxng-docker:searxng/searxng-docker:searxng-docker"
  "vllm:vllm-project/vllm:vllm"
)

mkdir -p "${STACK_ROOT}"

echo "Repo root:    ${REPO_ROOT}"
echo "Stack root:   ${STACK_ROOT}"
echo "GitHub owner: ${GITHUB_OWNER}"
echo "Use forks:    ${USE_FORKS}"
echo

for spec in "${repos[@]}"; do
  local_dir="${spec%%:*}"
  rest="${spec#*:}"
  upstream_repo="${rest%%:*}"
  fork_repo="${rest##*:}"

  if [[ "${USE_FORKS}" == "1" ]]; then
    clone_url="https://github.com/${GITHUB_OWNER}/${fork_repo}.git"
    upstream_url="https://github.com/${upstream_repo}.git"
  else
    clone_url="https://github.com/${upstream_repo}.git"
    upstream_url="https://github.com/${upstream_repo}.git"
  fi

  target_dir="${STACK_ROOT}/${local_dir}"

  if [[ -d "${target_dir}/.git" ]]; then
    echo "Skipping existing repo: ${target_dir}"
  else
    echo "Cloning ${clone_url} -> ${target_dir}"
    git clone "${clone_url}" "${target_dir}"
  fi

  if [[ "${USE_FORKS}" == "1" ]]; then
    if git -C "${target_dir}" remote get-url upstream >/dev/null 2>&1; then
      git -C "${target_dir}" remote set-url upstream "${upstream_url}"
    else
      git -C "${target_dir}" remote add upstream "${upstream_url}"
    fi
  fi
done

cat <<EOF

Done.

Cloned repos are local-only workspace dependencies and do not live inside the main git tree.

Examples:
  ./scripts/bootstrap_oss_stack.sh
  GITHUB_OWNER=pextacy ./scripts/bootstrap_oss_stack.sh
  USE_FORKS=0 ./scripts/bootstrap_oss_stack.sh

EOF
