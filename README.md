# Polymarket Monorepo

This repository is now the source of truth for the trading app, the legacy `agents/` code, and the vendored open-source infrastructure under `oss-stack/`.

## What Changed

- `src/polymarket_trader/` contains the current trader implementation
- `agents/` preserves the earlier project code that was previously only present in the parent workspace
- `oss-stack/` vendors the open-source infrastructure dependencies directly into this repo

This means collaborators can clone a single repository and see the full codebase without submodules or separate dependency forks.

## Layout

- `src/polymarket_trader/` — current autonomous trader code
- `agents/` — legacy Polymarket agents code
- `oss-stack/` — vendored Daytona, SearXNG, Lightpanda, Ollama, Qdrant, and vLLM
- `docs/` — setup, configuration, architecture, and PRD
- `scripts/` — local automation and helper scripts

## Getting Started

Use [docs/setup.md](docs/setup.md) for installation and runtime setup.

Use [docs/dependencies.md](docs/dependencies.md) for notes about the vendored infrastructure tree.
