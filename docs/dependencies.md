# Vendored Dependencies

The following repositories are now vendored directly inside this repository under `oss-stack/`:

- `daytona`
- `lightpanda-browser`
- `ollama`
- `qdrant`
- `searxng`
- `searxng-docker`
- `vllm`

The earlier project code is also vendored directly under `agents/`.

## Source Of Truth

`pextacy/polymarket` is now the monorepo source of truth for:

- the current trader in `src/polymarket_trader/`
- the earlier `agents/` code
- the open-source infrastructure snapshot in `oss-stack/`

This repo no longer relies on separate submodules or separate local clones for the primary collaboration workflow.

## Why This Changed

- collaborators needed one cloneable repo that already contains the full codebase
- submodules were intentionally avoided
- local-only workspace paths were not visible on GitHub

## Tradeoff

This repo is now much heavier than a thin app repo because it vendors large upstream projects. That is an intentional workflow tradeoff.

## Important

Local paths like:

- `oss-stack/`
- `agents/`

are now part of this repository's git tree.

Separate external forks can still exist for upstream sync or experimentation, but they are no longer the main documented setup path.

## Deprecated Bootstrap Script

The old bootstrap flow is no longer required for normal setup:

```bash
./scripts/bootstrap_oss_stack.sh
```

It is kept only as a compatibility helper and now points people back to the vendored monorepo layout.
