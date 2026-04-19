from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    OPENAI_COMPATIBLE = "openai_compatible"


class SearchProvider(str, Enum):
    SEARXNG = "searxng"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    llm_provider: LLMProvider = LLMProvider.OLLAMA
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_api_key: Optional[str] = Field(
        default=None,
        description="Optional API key for Ollama-compatible gateways; ignored by local Ollama",
    )
    openrouter_api_key: Optional[str] = Field(
        default=None, description="OpenRouter API key"
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openai_compatible_base_url: str = "http://localhost:8000/v1"
    openai_compatible_api_key: Optional[str] = None
    llm_model: str = "llama3.2:3b"
    llm_model_ranking: Optional[str] = None
    llm_model_forecasting: Optional[str] = None
    llm_model_extraction: Optional[str] = None

    @property
    def ranking_model(self) -> str:
        return self.llm_model_ranking or self.llm_model

    @property
    def forecasting_model(self) -> str:
        return self.llm_model_forecasting or self.llm_model

    @property
    def extraction_model(self) -> str:
        return self.llm_model_extraction or self.llm_model

    def llm_client_config(self) -> dict[str, object]:
        if self.llm_provider == LLMProvider.OLLAMA:
            return {
                "api_key": self.ollama_api_key or "ollama",
                "base_url": self.ollama_base_url,
                "default_headers": None,
            }

        if self.llm_provider == LLMProvider.OPENROUTER:
            if not self.openrouter_api_key:
                raise ValueError(
                    "OPENROUTER_API_KEY is required for llm_provider=openrouter"
                )
            return {
                "api_key": self.openrouter_api_key,
                "base_url": self.openrouter_base_url,
                "default_headers": {
                    "HTTP-Referer": "https://github.com/polymarket-trader",
                    "X-Title": "Polymarket Autonomous Trader",
                },
            }

        return {
            "api_key": self.openai_compatible_api_key or "local",
            "base_url": self.openai_compatible_base_url,
            "default_headers": None,
        }

    # Search
    search_provider: SearchProvider = SearchProvider.SEARXNG
    searxng_base_url: str = "http://localhost:8888"
    searxng_timeout_seconds: int = 15

    # Browser
    lightpanda_ws_url: str = "ws://localhost:9222"
    lightpanda_timeout_seconds: int = 30
    lightpanda_max_page_bytes: int = 2 * 1024 * 1024

    # Daytona runtime
    daytona_api_key: Optional[str] = None
    daytona_api_url: str = "https://app.daytona.io/api"
    daytona_target: Optional[str] = None
    daytona_sandbox_name_prefix: str = "polymarket-trader"
    daytona_sandbox_snapshot: Optional[str] = None
    daytona_sandbox_auto_stop_minutes: int = 15
    daytona_sandbox_command_timeout_seconds: int = 1800
    daytona_project_repo_url: Optional[str] = None
    daytona_project_ref: Optional[str] = None
    daytona_project_dir: str = "/home/daytona/polymarket"

    # Polymarket APIs
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    data_api_base_url: str = "https://data-api.polymarket.com"
    polymarket_chain_id: int = 137

    # Live trading keys (optional — only needed for live mode)
    polymarket_private_key: Optional[str] = None
    polymarket_proxy_address: Optional[str] = None

    # Trading mode
    trading_mode: TradingMode = TradingMode.PAPER

    # Risk limits
    risk_max_notional_per_market: float = 50.0
    risk_max_portfolio_exposure: float = 500.0
    risk_max_category_exposure: float = 150.0
    risk_max_daily_loss: float = 100.0
    risk_max_open_positions: int = 20
    risk_max_open_orders: int = 40
    risk_signal_staleness_seconds: int = 3600
    risk_expiry_no_trade_hours: int = 2
    risk_cooldown_after_losses: int = 3
    risk_cooldown_duration_seconds: int = 3600

    # Paper broker
    paper_initial_cash: float = 10_000.0
    paper_fill_slippage_bps: int = 20
    live_fill_slippage_bps: int = 10

    # Persistence
    database_url: str = "sqlite+aiosqlite:///./polymarket_trader.db"

    # Scan
    scan_interval_seconds: int = 900
    scan_market_limit: int = 100
    scan_min_liquidity_usdc: float = 500.0
    scan_min_volume_24h_usdc: float = 1000.0
    scan_max_research_sources: int = 5
    scan_min_edge_bps: int = 200

    # Observability
    log_level: str = "INFO"
    log_file: str = "logs/trader.log"

    @field_validator("trading_mode", mode="before")
    @classmethod
    def validate_trading_mode(cls, v: str) -> str:
        return v.lower() if isinstance(v, str) else v

    @field_validator(
        "daytona_sandbox_auto_stop_minutes",
        "daytona_sandbox_command_timeout_seconds",
    )
    @classmethod
    def validate_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("value must be non-negative")
        return v

    def require_live_keys(self) -> None:
        if not self.polymarket_private_key:
            raise ValueError("POLYMARKET_PRIVATE_KEY is required for live trading")
        if not self.polymarket_proxy_address:
            raise ValueError("POLYMARKET_PROXY_ADDRESS is required for live trading")

    def runtime_env(self) -> dict[str, str]:
        excluded = {
            "daytona_api_key",
            "daytona_api_url",
            "daytona_target",
            "daytona_sandbox_name_prefix",
            "daytona_sandbox_snapshot",
            "daytona_sandbox_auto_stop_minutes",
            "daytona_sandbox_command_timeout_seconds",
            "daytona_project_repo_url",
            "daytona_project_ref",
            "daytona_project_dir",
        }
        if self.trading_mode != TradingMode.LIVE:
            excluded.update({"polymarket_private_key", "polymarket_proxy_address"})

        env: dict[str, str] = {}
        for field_name in self.__class__.model_fields:
            if field_name in excluded:
                continue

            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, Enum):
                env[field_name.upper()] = value.value
            else:
                env[field_name.upper()] = str(value)

        env["PYTHONUNBUFFERED"] = "1"
        return env


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
