from __future__ import annotations

from polymarket_trader.config import LLMProvider, Settings, TradingMode


def test_ollama_is_default_provider() -> None:
    settings = Settings()
    config = settings.llm_client_config()

    assert settings.llm_provider == LLMProvider.OLLAMA
    assert config["base_url"] == "http://localhost:11434/v1"
    assert config["api_key"] == "ollama"


def test_openrouter_requires_key() -> None:
    settings = Settings(llm_provider=LLMProvider.OPENROUTER, openrouter_api_key=None)

    try:
        settings.llm_client_config()
    except ValueError as exc:
        assert "OPENROUTER_API_KEY" in str(exc)
    else:
        raise AssertionError(
            "Expected llm_client_config() to reject missing OpenRouter key"
        )


def test_openai_compatible_uses_dummy_local_key_when_unset() -> None:
    settings = Settings(
        llm_provider=LLMProvider.OPENAI_COMPATIBLE,
        openai_compatible_base_url="http://localhost:8000/v1",
    )
    config = settings.llm_client_config()

    assert config["base_url"] == "http://localhost:8000/v1"
    assert config["api_key"] == "local"


def test_runtime_env_excludes_daytona_and_live_keys_in_paper_mode() -> None:
    settings = Settings(
        trading_mode=TradingMode.PAPER,
        daytona_api_key="daytona-secret",
        polymarket_private_key="0xprivate",
        polymarket_proxy_address="0xproxy",
        llm_provider=LLMProvider.OPENROUTER,
        openrouter_api_key="or-key",
    )

    env = settings.runtime_env()

    assert env["TRADING_MODE"] == "paper"
    assert env["LLM_PROVIDER"] == "openrouter"
    assert env["OPENROUTER_API_KEY"] == "or-key"
    assert "DAYTONA_API_KEY" not in env
    assert "POLYMARKET_PRIVATE_KEY" not in env
    assert "POLYMARKET_PROXY_ADDRESS" not in env
