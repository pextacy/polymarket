from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from polymarket_trader.config import Settings, TradingMode
from polymarket_trader.runtime.daytona import DaytonaRuntime, RepoSpec


class FakeExecResult:
    def __init__(self, exit_code: int = 0, result: str = "") -> None:
        self.exit_code = exit_code
        self.result = result


class FakeProcess:
    def __init__(self, responses: list[FakeExecResult]) -> None:
        self.calls: list[dict[str, object]] = []
        self._responses = responses

    def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeExecResult:
        self.calls.append(
            {
                "command": command,
                "cwd": cwd,
                "env": env,
                "timeout": timeout,
            }
        )
        return self._responses.pop(0)


class FakeSandbox:
    def __init__(
        self,
        sandbox_id: str,
        *,
        state: str,
        role: str,
        process: FakeProcess,
    ) -> None:
        self.id = sandbox_id
        self.name = f"polymarket-trader-{role}"
        self.state = state
        self.labels = {"app": "polymarket-trader", "project": "polymarket-trader", "role": role}
        self.created_at = "2026-04-19T00:00:00Z"
        self.auto_stop_interval = 15
        self.process = process


class FakeClient:
    def __init__(self, sandboxes: list[FakeSandbox]) -> None:
        self._sandboxes = sandboxes
        self.last_labels: dict[str, str] | None = None
        self.last_limit: int | None = None
        self.created_params: object | None = None
        self.started_sandboxes: list[str] = []

    def list(self, labels: dict[str, str] | None = None, limit: int | None = None) -> SimpleNamespace:
        self.last_labels = labels
        self.last_limit = limit
        return SimpleNamespace(items=list(self._sandboxes), total=len(self._sandboxes))

    def create(self, params: object) -> FakeSandbox:
        self.created_params = params
        sandbox = FakeSandbox(
            "sandbox-created",
            state="started",
            role="scanner",
            process=FakeProcess(
                [
                    FakeExecResult(result="bootstrap complete\n"),
                    FakeExecResult(result="scan complete\n"),
                ]
            ),
        )
        self._sandboxes.append(sandbox)
        return sandbox

    def start(self, sandbox: FakeSandbox) -> None:
        self.started_sandboxes.append(sandbox.id)
        sandbox.state = "started"


def test_list_sandboxes_filters_by_project_labels(monkeypatch) -> None:
    sandbox = FakeSandbox(
        "sandbox-1",
        state="started",
        role="scanner",
        process=FakeProcess([]),
    )
    client = FakeClient([sandbox])
    runtime = DaytonaRuntime(Settings(daytona_api_key="key"))
    monkeypatch.setattr(runtime, "_build_client", lambda: client)

    sandboxes = runtime.list_sandboxes(role="scanner", limit=5)

    assert client.last_labels == {
        "app": "polymarket-trader",
        "project": "polymarket-trader",
        "role": "scanner",
    }
    assert client.last_limit == 5
    assert sandboxes[0].sandbox_id == "sandbox-1"
    assert sandboxes[0].role == "scanner"


def test_run_cli_reuses_and_starts_existing_sandbox(monkeypatch) -> None:
    process = FakeProcess(
        [
            FakeExecResult(result="bootstrap complete\n"),
            FakeExecResult(result="Top 7 Markets\n"),
        ]
    )
    sandbox = FakeSandbox(
        "sandbox-2",
        state="stopped",
        role="scanner",
        process=process,
    )
    client = FakeClient([sandbox])
    settings = Settings(
        daytona_api_key="key",
        trading_mode=TradingMode.PAPER,
        daytona_project_dir="/home/daytona/polymarket",
    )
    runtime = DaytonaRuntime(settings, repo_root=Path("/tmp/local-polymarket"))
    monkeypatch.setattr(runtime, "_build_client", lambda: client)
    monkeypatch.setattr(
        runtime,
        "_resolve_repo_spec",
        lambda: RepoSpec(
            url="https://github.com/pextacy/polymarket.git",
            ref="main",
            directory="/home/daytona/polymarket",
        ),
    )

    result = runtime.run_cli(["scan", "--top", "7"], role="scanner")

    assert client.started_sandboxes == ["sandbox-2"]
    assert process.calls[0]["cwd"] == "/home/daytona"
    assert "git clone https://github.com/pextacy/polymarket.git /home/daytona/polymarket" in str(process.calls[0]["command"])
    assert process.calls[1]["command"] == "python -m polymarket_trader.cli scan --top 7"
    assert process.calls[1]["cwd"] == "/home/daytona/polymarket"
    assert process.calls[1]["env"]["TRADING_MODE"] == "paper"
    assert "DAYTONA_API_KEY" not in process.calls[1]["env"]
    assert result.exit_code == 0
    assert result.output == "Top 7 Markets\n"


def test_run_cli_creates_new_sandbox_when_existing_one_is_broken(monkeypatch) -> None:
    broken = FakeSandbox(
        "sandbox-broken",
        state="error",
        role="scanner",
        process=FakeProcess([]),
    )
    client = FakeClient([broken])
    runtime = DaytonaRuntime(Settings(daytona_api_key="key"))
    monkeypatch.setattr(runtime, "_build_client", lambda: client)
    monkeypatch.setattr(runtime, "_create_params", lambda role: {"role": role})
    monkeypatch.setattr(
        runtime,
        "_resolve_repo_spec",
        lambda: RepoSpec(
            url="https://github.com/pextacy/polymarket.git",
            ref="main",
            directory="/home/daytona/polymarket",
        ),
    )

    runtime.run_cli(["scan"], role="scanner")

    assert client.created_params == {"role": "scanner"}
