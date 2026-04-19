#!/usr/bin/env bash

set -euo pipefail

services=("$@")

if [[ ${#services[@]} -eq 0 ]]; then
  services=(ollama searxng)
fi

wait_http() {
  local name="$1"
  local url="$2"
  local retries="${3:-60}"
  local sleep_seconds="${4:-2}"

  echo "Waiting for ${name} at ${url}"
  for _ in $(seq 1 "${retries}"); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      echo "${name} is ready"
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  echo "Timed out waiting for ${name} (${url})" >&2
  return 1
}

wait_docker_health() {
  local container="$1"
  local retries="${2:-60}"
  local sleep_seconds="${3:-2}"

  echo "Waiting for container health: ${container}"
  for _ in $(seq 1 "${retries}"); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container}" 2>/dev/null || true)"
    if [[ "${status}" == "healthy" || "${status}" == "running" ]]; then
      echo "${container} is ${status}"
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  echo "Timed out waiting for ${container}" >&2
  return 1
}

for service in "${services[@]}"; do
  case "${service}" in
    ollama)
      wait_http "ollama" "http://localhost:11434/api/tags"
      ;;
    searxng)
      wait_http "searxng" "http://localhost:8888/search?q=test&format=json"
      ;;
    lightpanda)
      wait_http "lightpanda" "http://localhost:9222/json/version"
      ;;
    postgres)
      wait_docker_health "polymarket-postgres"
      ;;
    redis)
      wait_docker_health "polymarket-redis"
      ;;
    *)
      echo "Unknown service: ${service}" >&2
      exit 1
      ;;
  esac
done
