from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings


APP_LABEL_VALUE = "polymarket-trader"
STARTED_STATES = {"started", "starting"}
STARTABLE_STATES = {"stopped", "archived"}
BROKEN_STATES = {"error", "build_failed", "destroyed", "destroying"}


class DaytonaRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoSpec:
    url: str
    ref: str
    directory: str


@dataclass(frozen=True)
class SandboxSummary:
    sandbox_id: str
    name: str
    role: str
    state: str
    created_at: str
    auto_stop_interval: int | float | None


@dataclass(frozen=True)
class DaytonaCommandResult:
    sandbox_id: str
    sandbox_name: str
    role: str
    command: str
    exit_code: int
    output: str


class DaytonaRuntime:
    def __init__(self, settings: Settings, repo_root: Path | None = None) -> None:
        self._s = settings
        self._repo_root = repo_root or Path(__file__).resolve().parents[3]

    def list_sandboxes(
        self,
        *,
        role: str | None = None,
        limit: int = 20,
    ) -> list[SandboxSummary]:
        client = self._build_client()
        result = client.list(labels=self._labels(role), limit=limit)
        return [self._to_summary(item) for item in result.items]

    def run_cli(
        self,
        args: list[str],
        *,
        role: str,
        reuse: bool = True,
    ) -> DaytonaCommandResult:
        if not args:
            raise DaytonaRuntimeError("At least one CLI argument is required")

        sandbox = self._ensure_sandbox(role=role, reuse=reuse)
        self._bootstrap_repo(sandbox)

        command = self._build_cli_command(args)
        result = sandbox.process.exec(
            command,
            cwd=self._s.daytona_project_dir,
            env=self._s.runtime_env(),
            timeout=self._s.daytona_sandbox_command_timeout_seconds,
        )
        exit_code = 0 if result.exit_code is None else int(result.exit_code)
        return DaytonaCommandResult(
            sandbox_id=str(sandbox.id),
            sandbox_name=str(getattr(sandbox, "name", "")),
            role=role,
            command=command,
            exit_code=exit_code,
            output=result.result or "",
        )

    def _ensure_sandbox(self, *, role: str, reuse: bool) -> Any:
        client = self._build_client()
        sandbox = None
        if reuse:
            result = client.list(labels=self._labels(role), limit=20)
            sandbox = self._select_existing_sandbox(result.items)

        if sandbox is None:
            sandbox = client.create(self._create_params(role))
        elif self._state_value(getattr(sandbox, "state", None)) in STARTABLE_STATES:
            client.start(sandbox)

        return sandbox

    def _select_existing_sandbox(self, sandboxes: list[Any]) -> Any | None:
        if not sandboxes:
            return None

        ranked = sorted(
            sandboxes,
            key=lambda sandbox: self._state_rank(self._state_value(getattr(sandbox, "state", None))),
        )
        candidate = ranked[0]
        if self._state_value(getattr(candidate, "state", None)) in BROKEN_STATES:
            return None
        return candidate

    def _bootstrap_repo(self, sandbox: Any) -> None:
        repo = self._resolve_repo_spec()
        bootstrap = self._build_bootstrap_command(repo)
        result = sandbox.process.exec(
            bootstrap,
            cwd="/home/daytona",
            env=self._s.runtime_env(),
            timeout=self._s.daytona_sandbox_command_timeout_seconds,
        )
        if result.exit_code not in (None, 0):
            raise DaytonaRuntimeError(
                "Daytona sandbox bootstrap failed:\n"
                f"{result.result or '(no output)'}"
            )

    def _build_client(self) -> Any:
        if not self._s.daytona_api_key:
            raise DaytonaRuntimeError(
                "DAYTONA_API_KEY is not set. Configure Daytona before using sandbox commands."
            )

        daytona_cls, config_cls, _ = self._sdk()
        config = config_cls(
            api_key=self._s.daytona_api_key,
            api_url=self._s.daytona_api_url,
            target=self._s.daytona_target,
        )
        return daytona_cls(config)

    def _create_params(self, role: str) -> Any:
        _, _, params_cls = self._sdk()
        return params_cls(
            name=self._sandbox_name(role),
            language="python",
            snapshot=self._s.daytona_sandbox_snapshot,
            labels=self._labels(role),
            auto_stop_interval=self._s.daytona_sandbox_auto_stop_minutes,
        )

    def _sdk(self) -> tuple[Any, Any, Any]:
        try:
            from daytona import Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams
        except ImportError as exc:
            raise DaytonaRuntimeError(
                "The `daytona` package is not installed. "
                'Run `python3.11 -m pip install -e ".[daytona]"` or `pip install daytona`.'
            ) from exc

        return Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams

    def _labels(self, role: str | None = None) -> dict[str, str]:
        labels = {
            "app": APP_LABEL_VALUE,
            "project": self._s.daytona_sandbox_name_prefix,
        }
        if role:
            labels["role"] = role
        return labels

    def _sandbox_name(self, role: str) -> str:
        return f"{self._s.daytona_sandbox_name_prefix}-{role}"

    def _resolve_repo_spec(self) -> RepoSpec:
        url = self._s.daytona_project_repo_url or self._detect_git_remote_url()
        ref = self._s.daytona_project_ref or self._detect_git_ref()
        return RepoSpec(
            url=self._normalize_git_url(url),
            ref=ref,
            directory=self._s.daytona_project_dir,
        )

    def _detect_git_remote_url(self) -> str:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=self._repo_root,
                capture_output=True,
                check=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise DaytonaRuntimeError(
                "Unable to detect the git remote for this repo. "
                "Set DAYTONA_PROJECT_REPO_URL explicitly."
            ) from exc

        return result.stdout.strip()

    def _detect_git_ref(self) -> str:
        branch = self._git_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if branch != "HEAD":
            return branch
        return self._git_output(["git", "rev-parse", "HEAD"])

    def _git_output(self, command: list[str]) -> str:
        try:
            result = subprocess.run(
                command,
                cwd=self._repo_root,
                capture_output=True,
                check=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise DaytonaRuntimeError(
                "Unable to detect the current git ref for this repo. "
                "Set DAYTONA_PROJECT_REF explicitly."
            ) from exc
        return result.stdout.strip()

    def _normalize_git_url(self, url: str) -> str:
        if url.startswith("git@github.com:"):
            return "https://github.com/" + url.removeprefix("git@github.com:")
        if url.startswith("ssh://git@github.com/"):
            return "https://github.com/" + url.removeprefix("ssh://git@github.com/")
        return url

    def _build_bootstrap_command(self, repo: RepoSpec) -> str:
        repo_url = shlex.quote(repo.url)
        repo_dir = shlex.quote(repo.directory)
        repo_parent = shlex.quote(str(Path(repo.directory).parent))
        repo_git_dir = shlex.quote(str(Path(repo.directory) / ".git"))
        ref = shlex.quote(repo.ref)

        return "\n".join(
            [
                "set -euo pipefail",
                f"mkdir -p {repo_parent}",
                f"if [ ! -d {repo_git_dir} ]; then git clone {repo_url} {repo_dir}; fi",
                f"cd {repo_dir}",
                "git fetch origin --prune",
                f"if git ls-remote --exit-code --heads origin {ref} >/dev/null 2>&1; then",
                f"  git checkout {ref}",
                f"  git pull --ff-only origin {ref}",
                "else",
                f"  git checkout {ref}",
                "fi",
                "python -m pip install -e .",
            ]
        )

    def _build_cli_command(self, args: list[str]) -> str:
        command = " ".join(shlex.quote(arg) for arg in args)
        return f"python -m polymarket_trader.cli {command}"

    def _to_summary(self, sandbox: Any) -> SandboxSummary:
        return SandboxSummary(
            sandbox_id=str(sandbox.id),
            name=str(getattr(sandbox, "name", "")),
            role=str(getattr(sandbox, "labels", {}).get("role", "")),
            state=self._state_value(getattr(sandbox, "state", None)),
            created_at=str(getattr(sandbox, "created_at", "—")),
            auto_stop_interval=getattr(sandbox, "auto_stop_interval", None),
        )

    def _state_rank(self, state: str) -> int:
        if state in STARTED_STATES:
            return 0
        if state in STARTABLE_STATES:
            return 1
        if state in BROKEN_STATES:
            return 3
        return 2

    def _state_value(self, state: Any) -> str:
        if state is None:
            return "unknown"
        return str(getattr(state, "value", state))
