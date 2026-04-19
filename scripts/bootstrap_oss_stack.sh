#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENDORED_STACK_ROOT="${REPO_ROOT}/oss-stack"

cat <<EOF

bootstrap_oss_stack.sh is deprecated.

This repository now vendors the infrastructure stack directly:
  ${VENDORED_STACK_ROOT}

You do not need to clone separate dependency repos for the normal workflow.

Use the vendored directories already in this repo:
  ${REPO_ROOT}/agents
  ${REPO_ROOT}/oss-stack

EOF
