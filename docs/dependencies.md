# External Dependencies

The following repositories are part of the local development stack for this project:

- `daytona`
- `lightpanda-browser`
- `ollama`
- `qdrant`
- `searxng`
- `searxng-docker`
- `vllm`

These repositories are intentionally **not** committed inside `pextacy/polymarket`.

Why:

- they are large upstream projects with their own release cycles
- vendoring them into this repo would make the repository unnecessarily heavy
- submodules were intentionally avoided for collaborator workflow reasons

## Important

Local paths like:

- `/Users/arhansubasi/agents/oss-stack`
- `/Users/arhansubasi/agents/agents`

are workspace directories on one machine. GitHub will not show them inside this repository because they are not part of this repo's git tree.

## Shared Setup

Use the bootstrap script from the project root:

```bash
./scripts/bootstrap_oss_stack.sh
```

By default it clones the stack into:

```bash
../oss-stack
```

It also supports selecting a GitHub owner:

```bash
GITHUB_OWNER=pextacy ./scripts/bootstrap_oss_stack.sh
```

Or cloning directly from upstream instead of forks:

```bash
USE_FORKS=0 ./scripts/bootstrap_oss_stack.sh
```

## Recommended Collaboration Model

If two people need shared ownership of the forked dependencies, the forks should live under:

- a shared GitHub organization, or
- the actual shared user account you both control

At the moment, the cloned dependency forks were created under the authenticated GitHub account used in this environment. If you want them under `pextacy`, authenticate as `pextacy` and rerun the forking flow, or transfer the existing forks there.
