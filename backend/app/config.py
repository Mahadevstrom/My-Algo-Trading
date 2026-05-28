from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from pydantic import BaseModel, Field

import os


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return int(raw_value)


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return float(raw_value)


def _env_list(name: str, default: str) -> list[str]:
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _env_optional_str(name: str) -> str | None:
    raw_value = os.getenv(name)
    if raw_value is None:
        return None
    cleaned = raw_value.strip()
    return cleaned or None


def _redact_url_credentials(value: str) -> str:
    parsed = urlsplit(value)
    if "@" not in parsed.netloc:
        return value
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    redacted_netloc = f"***:***@{host}"
    return urlunsplit((parsed.scheme, redacted_netloc, parsed.path, parsed.query, parsed.fragment))


class Settings(BaseModel):
    app_name: str = Field(default_factory=lambda: os.getenv("APP_NAME", "MyAlgoTrading"))
    env: str = Field(default_factory=lambda: os.getenv("ENV", "development"))
    trading_mode: str = Field(default_factory=lambda: os.getenv("TRADING_MODE", "PAPER").upper())
    allow_live_orders: bool = Field(default_factory=lambda: _env_bool("ALLOW_LIVE_ORDERS", False))
    enable_dhan_order_placement: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_DHAN_ORDER_PLACEMENT", False)
    )

    dhan_client_id: str | None = Field(default_factory=lambda: _env_optional_str("DHAN_CLIENT_ID"))
    dhan_access_token: str | None = Field(
        default_factory=lambda: _env_optional_str("DHAN_ACCESS_TOKEN")
    )
    enable_dhan_api_key_auth: bool = Field(default_factory=lambda: _env_bool("ENABLE_DHAN_API_KEY_AUTH", False))
    dhan_api_key: str | None = Field(default_factory=lambda: _env_optional_str("DHAN_API_KEY"))
    dhan_api_secret: str | None = Field(default_factory=lambda: _env_optional_str("DHAN_API_SECRET"))
    dhan_redirect_url: str = Field(
        default_factory=lambda: os.getenv(
            "DHAN_REDIRECT_URL",
            "http://127.0.0.1:8018/api/dhan-auth/callback",
        )
    )
    dhan_auth_base_url: str = Field(
        default_factory=lambda: os.getenv("DHAN_AUTH_BASE_URL", "https://auth.dhan.co")
    )
    dhan_token_cache_path: str = Field(
        default_factory=lambda: os.getenv(
            "DHAN_TOKEN_CACHE_PATH",
            str(BACKEND_DIR / "runtime" / "dhan_access_token.json"),
        )
    )
    dhan_trading_base_url: str = Field(
        default_factory=lambda: os.getenv("DHAN_TRADING_BASE_URL", "https://api.dhan.co/v2")
    )
    market_data_mode: str = Field(
        default_factory=lambda: os.getenv("MARKET_DATA_MODE", "DHAN").strip().upper()
    )
    dhan_data_enabled: bool = Field(default_factory=lambda: _env_bool("DHAN_DATA_ENABLED", True))
    dhan_base_url: str = Field(
        default_factory=lambda: os.getenv("DHAN_BASE_URL", "https://api.dhan.co/v2")
    )
    enable_dhan_rest_quota_guard: bool = Field(default_factory=lambda: _env_bool("ENABLE_DHAN_REST_QUOTA_GUARD", True))
    dhan_rest_quota_per_minute: int = Field(default_factory=lambda: _env_int("DHAN_REST_QUOTA_PER_MINUTE", 8))
    dhan_rest_min_gap_seconds: float = Field(default_factory=lambda: _env_float("DHAN_REST_MIN_GAP_SECONDS", 3.25))
    dhan_rest_response_cache_seconds: float = Field(
        default_factory=lambda: _env_float("DHAN_REST_RESPONSE_CACHE_SECONDS", 2.0)
    )
    dhan_rest_rate_limit_cooldown_seconds: float = Field(
        default_factory=lambda: _env_float("DHAN_REST_RATE_LIMIT_COOLDOWN_SECONDS", 30.0)
    )
    indstocks_enabled: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_INDSTOCKS", _env_bool("INDSTOCKS_ENABLED", False))
    )
    indstocks_access_token: str | None = Field(
        default_factory=lambda: _env_optional_str("INDSTOCKS_ACCESS_TOKEN")
    )
    indstocks_base_url: str = Field(
        default_factory=lambda: os.getenv("INDSTOCKS_BASE_URL", "https://api.indstocks.com")
    )
    indstocks_ws_price_url: str = Field(
        default_factory=lambda: os.getenv("INDSTOCKS_WS_PRICE_URL", "wss://ws-prices.indstocks.com/api/v1/ws/prices")
    )
    indstocks_ws_order_url: str = Field(
        default_factory=lambda: os.getenv("INDSTOCKS_WS_ORDER_URL", "wss://ws-order-updates.indstocks.com/api/v1/ws/trades")
    )
    indstocks_rest_cache_seconds: int = Field(default_factory=lambda: _env_int("INDSTOCKS_REST_CACHE_SECONDS", 5))
    indstocks_max_rest_checks_per_minute: int = Field(
        default_factory=lambda: _env_int("INDSTOCKS_MAX_REST_CHECKS_PER_MINUTE", 60)
    )
    indstocks_use_as_secondary_data: bool = Field(
        default_factory=lambda: _env_bool("INDSTOCKS_USE_AS_SECONDARY_DATA", True)
    )
    indstocks_enable_order_updates_ws: bool = Field(
        default_factory=lambda: _env_bool("INDSTOCKS_ENABLE_ORDER_UPDATES_WS", False)
    )
    indstocks_enable_order_placement: bool = Field(
        default_factory=lambda: _env_bool("INDSTOCKS_ENABLE_ORDER_PLACEMENT", False)
    )

    database_url: str = Field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./my_algo_trading.db")
    )
    db_pool_size: int = Field(default_factory=lambda: _env_int("DB_POOL_SIZE", _env_int("DATABASE_POOL_SIZE", 20)))
    db_max_overflow: int = Field(default_factory=lambda: _env_int("DB_MAX_OVERFLOW", _env_int("DATABASE_MAX_OVERFLOW", 30)))
    db_pool_timeout: int = Field(default_factory=lambda: _env_int("DB_POOL_TIMEOUT", _env_int("DATABASE_POOL_TIMEOUT", 30)))
    db_pool_recycle: int = Field(default_factory=lambda: _env_int("DB_POOL_RECYCLE", _env_int("DATABASE_POOL_RECYCLE", 1800)))
    db_pool_pre_ping: bool = Field(default_factory=lambda: _env_bool("DB_POOL_PRE_PING", True))

    max_trades_per_day: int = Field(default_factory=lambda: _env_int("MAX_TRADES_PER_DAY", 5))
    max_daily_loss: float = Field(default_factory=lambda: _env_float("MAX_DAILY_LOSS", 1000.0))
    max_qty_per_trade: int = Field(default_factory=lambda: _env_int("MAX_QTY_PER_TRADE", 1))
    enable_dhan_websocket: bool = Field(default_factory=lambda: _env_bool("ENABLE_DHAN_WEBSOCKET", False))
    dhan_ws_auto_start: bool = Field(default_factory=lambda: _env_bool("DHAN_WS_AUTO_START", False))
    dhan_ws_reconnect: bool = Field(default_factory=lambda: _env_bool("DHAN_WS_RECONNECT", True))
    dhan_ws_max_reconnect_attempts: int = Field(
        default_factory=lambda: _env_int("DHAN_WS_MAX_RECONNECT_ATTEMPTS", 10)
    )
    dhan_ws_reconnect_base_seconds: float = Field(
        default_factory=lambda: _env_float("DHAN_WS_RECONNECT_BASE_SECONDS", 2.0)
    )
    dhan_ws_stale_after_seconds: int = Field(
        default_factory=lambda: _env_int("DHAN_WS_STALE_AFTER_SECONDS", 10)
    )
    store_live_ticks: bool = Field(default_factory=lambda: _env_bool("STORE_LIVE_TICKS", False))
    live_tick_buffer_size: int = Field(default_factory=lambda: _env_int("LIVE_TICK_BUFFER_SIZE", 500))
    live_feed_auto_subscribe: bool = Field(default_factory=lambda: _env_bool("LIVE_FEED_AUTO_SUBSCRIBE", True))
    live_feed_default_symbols: str = Field(default_factory=lambda: os.getenv("LIVE_FEED_DEFAULT_SYMBOLS", "NIFTY,RELIANCE"))
    store_live_candles: bool = Field(default_factory=lambda: _env_bool("STORE_LIVE_CANDLES", False))
    live_candle_timeframes: str = Field(default_factory=lambda: os.getenv("LIVE_CANDLE_TIMEFRAMES", "1m,3m,5m,15m"))
    live_candle_max_history: int = Field(default_factory=lambda: _env_int("LIVE_CANDLE_MAX_HISTORY", 500))
    live_market_stale_after_seconds: int = Field(
        default_factory=lambda: _env_int("LIVE_MARKET_STALE_AFTER_SECONDS", 15)
    )
    live_monitor_auto_start: bool = Field(default_factory=lambda: _env_bool("LIVE_MONITOR_AUTO_START", False))
    enable_feed_watchdog: bool = Field(default_factory=lambda: _env_bool("ENABLE_FEED_WATCHDOG", True))
    feed_watchdog_interval_seconds: int = Field(default_factory=lambda: _env_int("FEED_WATCHDOG_INTERVAL_SECONDS", 10))
    feed_watchdog_auto_recover: bool = Field(default_factory=lambda: _env_bool("FEED_WATCHDOG_AUTO_RECOVER", True))
    feed_watchdog_restart_on_stale: bool = Field(default_factory=lambda: _env_bool("FEED_WATCHDOG_RESTART_ON_STALE", True))
    enable_startup_market_backfill: bool = Field(default_factory=lambda: _env_bool("ENABLE_STARTUP_MARKET_BACKFILL", True))
    market_backfill_symbols: str = Field(default_factory=lambda: os.getenv("MARKET_BACKFILL_SYMBOLS", "NIFTY"))
    market_backfill_source_interval: str = Field(default_factory=lambda: os.getenv("MARKET_BACKFILL_SOURCE_INTERVAL", "1"))
    market_backfill_start_time: str = Field(default_factory=lambda: os.getenv("MARKET_BACKFILL_START_TIME", "09:15:00"))
    market_backfill_end_time: str = Field(default_factory=lambda: os.getenv("MARKET_BACKFILL_END_TIME", "15:30:00"))
    market_backfill_run_after_market_open: bool = Field(
        default_factory=lambda: _env_bool("MARKET_BACKFILL_RUN_AFTER_MARKET_OPEN", True)
    )
    enable_setup_matcher: bool = Field(default_factory=lambda: _env_bool("ENABLE_SETUP_MATCHER", True))
    setup_matcher_evidence_window_seconds: int = Field(
        default_factory=lambda: _env_int("SETUP_MATCHER_EVIDENCE_WINDOW_SECONDS", 90)
    )
    setup_matcher_min_historical_trades: int = Field(
        default_factory=lambda: _env_int("SETUP_MATCHER_MIN_HISTORICAL_TRADES", 5)
    )
    setup_seeder_on_startup: bool = Field(default_factory=lambda: _env_bool("SETUP_SEEDER_ON_STARTUP", True))
    enable_decision_engine_v2: bool = Field(default_factory=lambda: _env_bool("ENABLE_DECISION_ENGINE_V2", True))
    decision_engine_v2_mode: str = Field(
        default_factory=lambda: os.getenv("DECISION_ENGINE_V2_MODE", "SHADOW").strip().upper()
    )
    decision_engine_v2_evidence_window_seconds: int = Field(
        default_factory=lambda: _env_int("DECISION_ENGINE_V2_EVIDENCE_WINDOW_SECONDS", 90)
    )
    decision_engine_v2_min_confidence: float = Field(
        default_factory=lambda: _env_float("DECISION_ENGINE_V2_MIN_CONFIDENCE", 0.62)
    )
    enable_test_tick_ingest: bool = Field(default_factory=lambda: _env_bool("ENABLE_TEST_TICK_INGEST", False))
    enable_data_quality_engine: bool = Field(default_factory=lambda: _env_bool("ENABLE_DATA_QUALITY_ENGINE", True))
    data_quality_rest_cross_check: bool = Field(default_factory=lambda: _env_bool("DATA_QUALITY_REST_CROSS_CHECK", True))
    data_quality_rest_cache_seconds: int = Field(
        default_factory=lambda: _env_int("DATA_QUALITY_REST_CACHE_SECONDS", 120)
    )
    data_quality_max_rest_checks_per_minute: int = Field(
        default_factory=lambda: _env_int("DATA_QUALITY_MAX_REST_CHECKS_PER_MINUTE", 6)
    )
    data_quality_ltp_mismatch_percent: float = Field(
        default_factory=lambda: _env_float("DATA_QUALITY_LTP_MISMATCH_PERCENT", 0.50)
    )
    data_quality_rest_mismatch_blocks_paper: bool = Field(
        default_factory=lambda: _env_bool("DATA_QUALITY_REST_MISMATCH_BLOCKS_PAPER", False)
    )
    data_quality_stale_after_seconds: int = Field(
        default_factory=lambda: _env_int("DATA_QUALITY_STALE_AFTER_SECONDS", 15)
    )
    data_quality_price_spike_percent: float = Field(
        default_factory=lambda: _env_float("DATA_QUALITY_PRICE_SPIKE_PERCENT", 3.0)
    )
    data_quality_min_candles_for_gap_check: int = Field(
        default_factory=lambda: _env_int("DATA_QUALITY_MIN_CANDLES_FOR_GAP_CHECK", 3)
    )
    data_quality_max_history: int = Field(default_factory=lambda: _env_int("DATA_QUALITY_MAX_HISTORY", 500))
    data_quality_audit_throttle_seconds: int = Field(
        default_factory=lambda: _env_int("DATA_QUALITY_AUDIT_THROTTLE_SECONDS", 60)
    )
    enable_signal_engine_v2: bool = Field(default_factory=lambda: _env_bool("ENABLE_SIGNAL_ENGINE_V2", True))
    enable_specialist_engines: bool = Field(default_factory=lambda: _env_bool("ENABLE_SPECIALIST_ENGINES", True))
    oc_engine_premium_strong_threshold: float = Field(
        default_factory=lambda: _env_float("OC_ENGINE_PREMIUM_STRONG_THRESHOLD", 50.0)
    )
    oc_engine_premium_weak_threshold: float = Field(
        default_factory=lambda: _env_float("OC_ENGINE_PREMIUM_WEAK_THRESHOLD", 20.0)
    )
    oc_engine_pcr_bearish_threshold: float = Field(
        default_factory=lambda: _env_float("OC_ENGINE_PCR_BEARISH_THRESHOLD", 1.2)
    )
    oc_engine_pcr_bullish_threshold: float = Field(
        default_factory=lambda: _env_float("OC_ENGINE_PCR_BULLISH_THRESHOLD", 0.8)
    )
    enable_context_classifier: bool = Field(default_factory=lambda: _env_bool("ENABLE_CONTEXT_CLASSIFIER", True))
    context_vix_high_threshold: float = Field(default_factory=lambda: _env_float("CONTEXT_VIX_HIGH_THRESHOLD", 18.0))
    context_vix_low_threshold: float = Field(default_factory=lambda: _env_float("CONTEXT_VIX_LOW_THRESHOLD", 13.0))
    context_gap_large_threshold: float = Field(default_factory=lambda: _env_float("CONTEXT_GAP_LARGE_THRESHOLD", 1.0))
    context_gap_small_threshold: float = Field(default_factory=lambda: _env_float("CONTEXT_GAP_SMALL_THRESHOLD", 0.5))
    context_expiry_afternoon_hour: int = Field(default_factory=lambda: _env_int("CONTEXT_EXPIRY_AFTERNOON_HOUR", 13))
    context_expiry_afternoon_minute: int = Field(default_factory=lambda: _env_int("CONTEXT_EXPIRY_AFTERNOON_MINUTE", 30))
    context_expiry_morning_cutoff_hour: int = Field(default_factory=lambda: _env_int("CONTEXT_EXPIRY_MORNING_CUTOFF_HOUR", 11))
    context_expiry_morning_cutoff_minute: int = Field(default_factory=lambda: _env_int("CONTEXT_EXPIRY_MORNING_CUTOFF_MINUTE", 30))
    ms_engine_ema_fast: int = Field(default_factory=lambda: _env_int("MS_ENGINE_EMA_FAST", 9))
    ms_engine_ema_slow: int = Field(default_factory=lambda: _env_int("MS_ENGINE_EMA_SLOW", 21))
    ms_engine_ema_trend: int = Field(default_factory=lambda: _env_int("MS_ENGINE_EMA_TREND", 50))
    ms_engine_atr_period: int = Field(default_factory=lambda: _env_int("MS_ENGINE_ATR_PERIOD", 14))
    ms_engine_min_candles: int = Field(default_factory=lambda: _env_int("MS_ENGINE_MIN_CANDLES", 10))
    ms_engine_ranging_crossings: int = Field(default_factory=lambda: _env_int("MS_ENGINE_RANGING_CROSSINGS", 3))
    ms_engine_strong_candle_ratio: float = Field(
        default_factory=lambda: _env_float("MS_ENGINE_STRONG_CANDLE_RATIO", 0.60)
    )
    ms_engine_high_atr_threshold: float = Field(
        default_factory=lambda: _env_float("MS_ENGINE_HIGH_ATR_THRESHOLD", 0.004)
    )
    enable_nifty_momentum_engine: bool = Field(default_factory=lambda: _env_bool("ENABLE_NIFTY_MOMENTUM_ENGINE", True))
    signal_v2_min_score: int = Field(default_factory=lambda: _env_int("SIGNAL_V2_MIN_SCORE", 75))
    signal_v2_primary_timeframe: str = Field(default_factory=lambda: os.getenv("SIGNAL_V2_PRIMARY_TIMEFRAME", "5m"))
    signal_v2_confirm_timeframe: str = Field(default_factory=lambda: os.getenv("SIGNAL_V2_CONFIRM_TIMEFRAME", "15m"))
    signal_v2_entry_timeframes: str = Field(default_factory=lambda: os.getenv("SIGNAL_V2_ENTRY_TIMEFRAMES", "1m,3m"))
    signal_v2_min_1m_candles: int = Field(default_factory=lambda: _env_int("SIGNAL_V2_MIN_1M_CANDLES", 3))
    signal_v2_min_3m_candles: int = Field(default_factory=lambda: _env_int("SIGNAL_V2_MIN_3M_CANDLES", 2))
    signal_v2_min_5m_candles: int = Field(default_factory=lambda: _env_int("SIGNAL_V2_MIN_5M_CANDLES", 2))
    signal_v2_min_15m_candles: int = Field(default_factory=lambda: _env_int("SIGNAL_V2_MIN_15M_CANDLES", 1))
    signal_v2_paper_min_score: int = Field(default_factory=lambda: _env_int("SIGNAL_V2_PAPER_MIN_SCORE", 70))
    signal_v2_require_data_quality: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_REQUIRE_DATA_QUALITY", True)
    )
    signal_v2_allow_warning_data_quality: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_ALLOW_WARNING_DATA_QUALITY", False)
    )
    signal_v2_use_option_chain: bool = Field(default_factory=lambda: _env_bool("SIGNAL_V2_USE_OPTION_CHAIN", True))
    signal_v2_use_live_candles: bool = Field(default_factory=lambda: _env_bool("SIGNAL_V2_USE_LIVE_CANDLES", True))
    signal_v2_use_indstocks_cross_check: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_USE_INDSTOCKS_CROSS_CHECK", True)
    )
    signal_v2_require_indstocks_confirmation: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_REQUIRE_INDSTOCKS_CONFIRMATION", False)
    )
    signal_v2_indstocks_mismatch_percent: float = Field(
        default_factory=lambda: _env_float("SIGNAL_V2_INDSTOCKS_MISMATCH_PERCENT", 0.20)
    )
    signal_v2_market_session_only: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_MARKET_SESSION_ONLY", True)
    )
    signal_v2_no_trade_on_kill_switch: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_NO_TRADE_ON_KILL_SWITCH", True)
    )
    enable_signal_v2_session_gate: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_SIGNAL_V2_SESSION_GATE", True)
    )
    signal_v2_session_gate_hard_block: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_SESSION_GATE_HARD_BLOCK", True)
    )
    signal_v2_allow_analysis_when_session_blocked: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_ALLOW_ANALYSIS_WHEN_SESSION_BLOCKED", True)
    )
    enable_live_paper_simulator: bool = Field(default_factory=lambda: _env_bool("ENABLE_LIVE_PAPER_SIMULATOR", False))
    live_paper_auto_start: bool = Field(default_factory=lambda: _env_bool("LIVE_PAPER_AUTO_START", False))
    live_paper_underlying: str = Field(default_factory=lambda: os.getenv("LIVE_PAPER_UNDERLYING", "NIFTY").strip().upper())
    live_paper_virtual_capital: float = Field(default_factory=lambda: _env_float("LIVE_PAPER_VIRTUAL_CAPITAL", 100000.0))
    live_paper_max_open_trades: int = Field(default_factory=lambda: _env_int("LIVE_PAPER_MAX_OPEN_TRADES", 1))
    live_paper_max_trades_per_day: int = Field(default_factory=lambda: _env_int("LIVE_PAPER_MAX_TRADES_PER_DAY", 5))
    live_paper_max_daily_loss: float = Field(default_factory=lambda: _env_float("LIVE_PAPER_MAX_DAILY_LOSS", 1000.0))
    live_paper_max_loss_per_trade: float = Field(default_factory=lambda: _env_float("LIVE_PAPER_MAX_LOSS_PER_TRADE", 500.0))
    live_paper_default_qty: int = Field(default_factory=lambda: _env_int("LIVE_PAPER_DEFAULT_QTY", 1))
    live_paper_cooldown_seconds: int = Field(default_factory=lambda: _env_int("LIVE_PAPER_COOLDOWN_SECONDS", 300))
    live_paper_signal_check_interval_seconds: int = Field(
        default_factory=lambda: _env_int("LIVE_PAPER_SIGNAL_CHECK_INTERVAL_SECONDS", 30)
    )
    live_paper_mtm_interval_seconds: int = Field(default_factory=lambda: _env_int("LIVE_PAPER_MTM_INTERVAL_SECONDS", 5))
    live_paper_require_data_quality_ok: bool = Field(
        default_factory=lambda: _env_bool("LIVE_PAPER_REQUIRE_DATA_QUALITY_OK", True)
    )
    live_paper_allow_warning_data_quality: bool = Field(
        default_factory=lambda: _env_bool("LIVE_PAPER_ALLOW_WARNING_DATA_QUALITY", False)
    )
    live_paper_min_signal_score: int = Field(default_factory=lambda: _env_int("LIVE_PAPER_MIN_SIGNAL_SCORE", 75))
    live_paper_market_session_only: bool = Field(
        default_factory=lambda: _env_bool("LIVE_PAPER_MARKET_SESSION_ONLY", True)
    )
    confidence_calibration_lookback_days: int = Field(
        default_factory=lambda: _env_int("CONFIDENCE_CALIBRATION_LOOKBACK_DAYS", 30)
    )
    confidence_calibration_min_trades: int = Field(
        default_factory=lambda: _env_int("CONFIDENCE_CALIBRATION_MIN_TRADES", 20)
    )
    filter_scorer_lookback_days: int = Field(
        default_factory=lambda: _env_int("FILTER_SCORER_LOOKBACK_DAYS", 30)
    )
    filter_scorer_min_trades: int = Field(
        default_factory=lambda: _env_int("FILTER_SCORER_MIN_TRADES", 15)
    )
    filter_scorer_min_trades_per_filter: int = Field(
        default_factory=lambda: _env_int("FILTER_SCORER_MIN_TRADES_PER_FILTER", 5)
    )
    enable_agent_evolution_engine: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_AGENT_EVOLUTION_ENGINE", True)
    )
    agent_evolution_min_trades: int = Field(
        default_factory=lambda: _env_int("AGENT_EVOLUTION_MIN_TRADES", 20)
    )
    agent_evolution_lookback_days: int = Field(
        default_factory=lambda: _env_int("AGENT_EVOLUTION_LOOKBACK_DAYS", 30)
    )
    agent_evolution_auto_apply: bool = Field(
        default_factory=lambda: _env_bool("AGENT_EVOLUTION_AUTO_APPLY", False)
    )
    agent_evolution_max_recs_per_run: int = Field(
        default_factory=lambda: _env_int("AGENT_EVOLUTION_MAX_RECS_PER_RUN", 5)
    )
    agent_evolution_nightly_run: bool = Field(
        default_factory=lambda: _env_bool("AGENT_EVOLUTION_NIGHTLY_RUN", True)
    )
    agent_evolution_run_time_ist: str = Field(
        default_factory=lambda: os.getenv("AGENT_EVOLUTION_RUN_TIME_IST", "18:30")
    )
    live_paper_auto_exit_on_stale_data: bool = Field(
        default_factory=lambda: _env_bool("LIVE_PAPER_AUTO_EXIT_ON_STALE_DATA", True)
    )
    live_paper_stale_exit_seconds: int = Field(default_factory=lambda: _env_int("LIVE_PAPER_STALE_EXIT_SECONDS", 30))
    live_paper_stop_loss_percent: float = Field(default_factory=lambda: _env_float("LIVE_PAPER_STOP_LOSS_PERCENT", 20.0))
    live_paper_target_percent: float = Field(default_factory=lambda: _env_float("LIVE_PAPER_TARGET_PERCENT", 30.0))
    live_paper_trailing_enabled: bool = Field(default_factory=lambda: _env_bool("LIVE_PAPER_TRAILING_ENABLED", True))
    live_paper_trailing_activate_percent: float = Field(
        default_factory=lambda: _env_float("LIVE_PAPER_TRAILING_ACTIVATE_PERCENT", 15.0)
    )
    live_paper_trailing_gap_percent: float = Field(
        default_factory=lambda: _env_float("LIVE_PAPER_TRAILING_GAP_PERCENT", 8.0)
    )
    live_paper_time_exit_minutes: int = Field(default_factory=lambda: _env_int("LIVE_PAPER_TIME_EXIT_MINUTES", 20))
    live_paper_exit_before_market_close_minutes: int = Field(
        default_factory=lambda: _env_int("LIVE_PAPER_EXIT_BEFORE_MARKET_CLOSE_MINUTES", 10)
    )
    live_paper_use_indstocks_cross_check: bool = Field(
        default_factory=lambda: _env_bool("LIVE_PAPER_USE_INDSTOCKS_CROSS_CHECK", True)
    )
    live_paper_require_indstocks_confirmation: bool = Field(
        default_factory=lambda: _env_bool("LIVE_PAPER_REQUIRE_INDSTOCKS_CONFIRMATION", False)
    )
    enable_live_paper_session_gate: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_LIVE_PAPER_SESSION_GATE", True)
    )
    live_paper_block_entries_outside_session: bool = Field(
        default_factory=lambda: _env_bool("LIVE_PAPER_BLOCK_ENTRIES_OUTSIDE_SESSION", True)
    )
    live_paper_allow_exits_outside_entry_session: bool = Field(
        default_factory=lambda: _env_bool("LIVE_PAPER_ALLOW_EXITS_OUTSIDE_ENTRY_SESSION", True)
    )
    live_paper_allow_square_off_review: bool = Field(
        default_factory=lambda: _env_bool("LIVE_PAPER_ALLOW_SQUARE_OFF_REVIEW", True)
    )
    enable_strategy_evaluation: bool = Field(default_factory=lambda: _env_bool("ENABLE_STRATEGY_EVALUATION", True))
    strategy_eval_min_sample_size: int = Field(default_factory=lambda: _env_int("STRATEGY_EVAL_MIN_SAMPLE_SIZE", 20))
    strategy_eval_healthy_profit_factor: float = Field(
        default_factory=lambda: _env_float("STRATEGY_EVAL_HEALTHY_PROFIT_FACTOR", 1.4)
    )
    strategy_eval_max_acceptable_drawdown: float = Field(
        default_factory=lambda: _env_float("STRATEGY_EVAL_MAX_ACCEPTABLE_DRAWDOWN", 10.0)
    )
    strategy_eval_min_expectancy: float = Field(default_factory=lambda: _env_float("STRATEGY_EVAL_MIN_EXPECTANCY", 0.0))
    strategy_eval_lookback_days: int = Field(default_factory=lambda: _env_int("STRATEGY_EVAL_LOOKBACK_DAYS", 30))
    enable_market_flow_engine: bool = Field(default_factory=lambda: _env_bool("ENABLE_MARKET_FLOW_ENGINE", True))
    market_flow_default_symbol: str = Field(
        default_factory=lambda: os.getenv("MARKET_FLOW_DEFAULT_SYMBOL", "NIFTY").strip().upper()
    )
    market_flow_use_live_candles: bool = Field(
        default_factory=lambda: _env_bool("MARKET_FLOW_USE_LIVE_CANDLES", True)
    )
    market_flow_use_data_quality: bool = Field(
        default_factory=lambda: _env_bool("MARKET_FLOW_USE_DATA_QUALITY", True)
    )
    market_flow_use_indstocks_cross_check: bool = Field(
        default_factory=lambda: _env_bool("MARKET_FLOW_USE_INDSTOCKS_CROSS_CHECK", True)
    )
    market_flow_require_indstocks: bool = Field(
        default_factory=lambda: _env_bool("MARKET_FLOW_REQUIRE_INDSTOCKS", False)
    )
    market_flow_max_chain_strikes: int = Field(default_factory=lambda: _env_int("MARKET_FLOW_MAX_CHAIN_STRIKES", 40))
    market_flow_near_strike_range: int = Field(default_factory=lambda: _env_int("MARKET_FLOW_NEAR_STRIKE_RANGE", 5))
    market_flow_trap_risk_distance_percent: float = Field(
        default_factory=lambda: _env_float("MARKET_FLOW_TRAP_RISK_DISTANCE_PERCENT", 0.35)
    )
    market_flow_min_liquidity_score: int = Field(
        default_factory=lambda: _env_int("MARKET_FLOW_MIN_LIQUIDITY_SCORE", 60)
    )
    market_flow_cache_seconds: int = Field(default_factory=lambda: _env_int("MARKET_FLOW_CACHE_SECONDS", 5))
    market_flow_enable_audit: bool = Field(default_factory=lambda: _env_bool("MARKET_FLOW_ENABLE_AUDIT", True))
    market_flow_audit_throttle_seconds: int = Field(
        default_factory=lambda: _env_int("MARKET_FLOW_AUDIT_THROTTLE_SECONDS", 60)
    )
    enable_option_chain_snapshots: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_OPTION_CHAIN_SNAPSHOTS", True)
    )
    option_chain_snapshot_default_symbol: str = Field(
        default_factory=lambda: os.getenv("OPTION_CHAIN_SNAPSHOT_DEFAULT_SYMBOL", "NIFTY").strip().upper()
    )
    option_chain_snapshot_interval_seconds: int = Field(
        default_factory=lambda: _env_int("OPTION_CHAIN_SNAPSHOT_INTERVAL_SECONDS", 60)
    )
    option_chain_snapshot_max_strikes: int = Field(
        default_factory=lambda: _env_int("OPTION_CHAIN_SNAPSHOT_MAX_STRIKES", 80)
    )
    option_chain_snapshot_strike_range: int = Field(
        default_factory=lambda: _env_int("OPTION_CHAIN_SNAPSHOT_STRIKE_RANGE", 40)
    )
    option_chain_snapshot_store_raw: bool = Field(
        default_factory=lambda: _env_bool("OPTION_CHAIN_SNAPSHOT_STORE_RAW", False)
    )
    option_chain_snapshot_retention_days: int = Field(
        default_factory=lambda: _env_int("OPTION_CHAIN_SNAPSHOT_RETENTION_DAYS", 10)
    )
    option_chain_snapshot_auto_capture: bool = Field(
        default_factory=lambda: _env_bool("OPTION_CHAIN_SNAPSHOT_AUTO_CAPTURE", False)
    )
    option_chain_snapshot_min_seconds_between: int = Field(
        default_factory=lambda: _env_int("OPTION_CHAIN_SNAPSHOT_MIN_SECONDS_BETWEEN", 30)
    )
    option_chain_snapshot_audit_throttle_seconds: int = Field(
        default_factory=lambda: _env_int("OPTION_CHAIN_SNAPSHOT_AUDIT_THROTTLE_SECONDS", 60)
    )
    enable_signal_v2_market_flow_gate: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_SIGNAL_V2_MARKET_FLOW_GATE", True)
    )
    signal_v2_use_market_flow: bool = Field(default_factory=lambda: _env_bool("SIGNAL_V2_USE_MARKET_FLOW", True))
    signal_v2_require_market_flow: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_REQUIRE_MARKET_FLOW", False)
    )
    signal_v2_market_flow_min_score: int = Field(
        default_factory=lambda: _env_int("SIGNAL_V2_MARKET_FLOW_MIN_SCORE", 55)
    )
    signal_v2_market_flow_confirm_bonus: int = Field(
        default_factory=lambda: _env_int("SIGNAL_V2_MARKET_FLOW_CONFIRM_BONUS", 8)
    )
    signal_v2_market_flow_conflict_penalty: int = Field(
        default_factory=lambda: _env_int("SIGNAL_V2_MARKET_FLOW_CONFLICT_PENALTY", 15)
    )
    signal_v2_market_flow_high_trap_penalty: int = Field(
        default_factory=lambda: _env_int("SIGNAL_V2_MARKET_FLOW_HIGH_TRAP_PENALTY", 25)
    )
    signal_v2_no_trade_on_high_trap: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_NO_TRADE_ON_HIGH_TRAP", True)
    )
    signal_v2_allow_partial_market_flow: bool = Field(
        default_factory=lambda: _env_bool("SIGNAL_V2_ALLOW_PARTIAL_MARKET_FLOW", True)
    )
    signal_v2_require_oi_change: bool = Field(default_factory=lambda: _env_bool("SIGNAL_V2_REQUIRE_OI_CHANGE", False))
    signal_v2_oi_change_bonus: int = Field(default_factory=lambda: _env_int("SIGNAL_V2_OI_CHANGE_BONUS", 5))
    signal_v2_near_resistance_call_penalty: int = Field(
        default_factory=lambda: _env_int("SIGNAL_V2_NEAR_RESISTANCE_CALL_PENALTY", 10)
    )
    signal_v2_near_support_put_penalty: int = Field(
        default_factory=lambda: _env_int("SIGNAL_V2_NEAR_SUPPORT_PUT_PENALTY", 10)
    )
    enable_participant_flow_engine: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_PARTICIPANT_FLOW_ENGINE", True)
    )
    participant_flow_default_symbol: str = Field(
        default_factory=lambda: os.getenv("PARTICIPANT_FLOW_DEFAULT_SYMBOL", "NIFTY").strip().upper()
    )
    participant_flow_data_mode: str = Field(
        default_factory=lambda: os.getenv("PARTICIPANT_FLOW_DATA_MODE", "NSE_PUBLIC").strip().upper()
    )
    participant_flow_allow_web_fetch: bool = Field(
        default_factory=lambda: _env_bool("PARTICIPANT_FLOW_ALLOW_WEB_FETCH", True)
    )
    participant_flow_store_raw: bool = Field(default_factory=lambda: _env_bool("PARTICIPANT_FLOW_STORE_RAW", False))
    participant_flow_lookback_days: int = Field(default_factory=lambda: _env_int("PARTICIPANT_FLOW_LOOKBACK_DAYS", 10))
    participant_flow_cache_seconds: int = Field(default_factory=lambda: _env_int("PARTICIPANT_FLOW_CACHE_SECONDS", 30))
    participant_flow_enable_audit: bool = Field(
        default_factory=lambda: _env_bool("PARTICIPANT_FLOW_ENABLE_AUDIT", True)
    )
    participant_flow_audit_throttle_seconds: int = Field(
        default_factory=lambda: _env_int("PARTICIPANT_FLOW_AUDIT_THROTTLE_SECONDS", 60)
    )
    participant_flow_min_records_for_bias: int = Field(
        default_factory=lambda: _env_int("PARTICIPANT_FLOW_MIN_RECORDS_FOR_BIAS", 1)
    )
    participant_flow_warn_if_data_older_than_days: int = Field(
        default_factory=lambda: _env_int("PARTICIPANT_FLOW_WARN_IF_DATA_OLDER_THAN_DAYS", 2)
    )
    enable_participant_flow_sample_data: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_PARTICIPANT_FLOW_SAMPLE_DATA", False)
    )
    enable_sector_breadth_engine: bool = Field(
        default_factory=lambda: _env_bool("ENABLE_SECTOR_BREADTH_ENGINE", True)
    )
    sector_breadth_default_index: str = Field(
        default_factory=lambda: os.getenv("SECTOR_BREADTH_DEFAULT_INDEX", "NIFTY").strip().upper()
    )
    sector_breadth_cache_seconds: int = Field(default_factory=lambda: _env_int("SECTOR_BREADTH_CACHE_SECONDS", 10))
    sector_breadth_max_symbols_per_run: int = Field(
        default_factory=lambda: _env_int("SECTOR_BREADTH_MAX_SYMBOLS_PER_RUN", 80)
    )
    sector_breadth_use_dhan: bool = Field(default_factory=lambda: _env_bool("SECTOR_BREADTH_USE_DHAN", True))
    sector_breadth_use_indstocks_cross_check: bool = Field(
        default_factory=lambda: _env_bool("SECTOR_BREADTH_USE_INDSTOCKS_CROSS_CHECK", True)
    )
    sector_breadth_require_indstocks: bool = Field(
        default_factory=lambda: _env_bool("SECTOR_BREADTH_REQUIRE_INDSTOCKS", False)
    )
    sector_breadth_enable_audit: bool = Field(
        default_factory=lambda: _env_bool("SECTOR_BREADTH_ENABLE_AUDIT", True)
    )
    sector_breadth_audit_throttle_seconds: int = Field(
        default_factory=lambda: _env_int("SECTOR_BREADTH_AUDIT_THROTTLE_SECONDS", 60)
    )
    sector_breadth_min_symbols_per_sector: int = Field(
        default_factory=lambda: _env_int("SECTOR_BREADTH_MIN_SYMBOLS_PER_SECTOR", 2)
    )
    sector_breadth_min_sectors_for_market_bias: int = Field(
        default_factory=lambda: _env_int("SECTOR_BREADTH_MIN_SECTORS_FOR_MARKET_BIAS", 3)
    )
    sector_breadth_heavyweight_mode: str = Field(
        default_factory=lambda: os.getenv("SECTOR_BREADTH_HEAVYWEIGHT_MODE", "EQUAL_WEIGHT").strip().upper()
    )
    sector_breadth_allow_partial_data: bool = Field(
        default_factory=lambda: _env_bool("SECTOR_BREADTH_ALLOW_PARTIAL_DATA", True)
    )
    enable_reporting_engine: bool = Field(default_factory=lambda: _env_bool("ENABLE_REPORTING_ENGINE", True))
    reports_default_lookback_days: int = Field(default_factory=lambda: _env_int("REPORTS_DEFAULT_LOOKBACK_DAYS", 7))
    reports_daily_review_lookback_days: int = Field(
        default_factory=lambda: _env_int("REPORTS_DAILY_REVIEW_LOOKBACK_DAYS", 1)
    )
    reports_audit_lookback_days: int = Field(default_factory=lambda: _env_int("REPORTS_AUDIT_LOOKBACK_DAYS", 7))
    reports_max_audit_events: int = Field(default_factory=lambda: _env_int("REPORTS_MAX_AUDIT_EVENTS", 100))
    reports_include_test_data_warnings: bool = Field(
        default_factory=lambda: _env_bool("REPORTS_INCLUDE_TEST_DATA_WARNINGS", True)
    )
    reports_store_snapshots: bool = Field(default_factory=lambda: _env_bool("REPORTS_STORE_SNAPSHOTS", False))
    reports_supported_formats: str = Field(default_factory=lambda: os.getenv("REPORTS_SUPPORTED_FORMATS", "json,csv,md"))
    reports_enable_audit: bool = Field(default_factory=lambda: _env_bool("REPORTS_ENABLE_AUDIT", True))
    reports_audit_throttle_seconds: int = Field(
        default_factory=lambda: _env_int("REPORTS_AUDIT_THROTTLE_SECONDS", 60)
    )
    enable_ai_analyst: bool = Field(default_factory=lambda: _env_bool("ENABLE_AI_ANALYST", True))
    ai_provider: str = Field(default_factory=lambda: os.getenv("AI_PROVIDER", "gemini"))
    gemini_api_key: str | None = Field(default_factory=lambda: _env_optional_str("GEMINI_API_KEY"))
    gemini_model_name: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash"))
    openai_api_key: str | None = Field(default_factory=lambda: _env_optional_str("OPENAI_API_KEY"))
    openai_base_url: str | None = Field(default_factory=lambda: _env_optional_str("OPENAI_BASE_URL"))
    openai_model_name: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"))
    ollama_base_url: str = Field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"))
    ollama_model_name: str = Field(default_factory=lambda: os.getenv("OLLAMA_MODEL_NAME", "qwen2.5-coder:7b"))
    enable_session_gate: bool = Field(default_factory=lambda: _env_bool("ENABLE_SESSION_GATE", True))
    session_gate_timezone: str = Field(default_factory=lambda: os.getenv("SESSION_GATE_TIMEZONE", "Asia/Kolkata"))
    session_pre_market_start: str = Field(default_factory=lambda: os.getenv("SESSION_PRE_MARKET_START", "09:00"))
    session_market_open: str = Field(default_factory=lambda: os.getenv("SESSION_MARKET_OPEN", "09:15"))
    session_first_trade_time: str = Field(default_factory=lambda: os.getenv("SESSION_FIRST_TRADE_TIME", "09:20"))
    session_midday_start: str = Field(default_factory=lambda: os.getenv("SESSION_MIDDAY_START", "11:00"))
    session_midday_end: str = Field(default_factory=lambda: os.getenv("SESSION_MIDDAY_END", "13:45"))
    session_late_session_start: str = Field(default_factory=lambda: os.getenv("SESSION_LATE_SESSION_START", "14:45"))
    session_no_new_trade_after: str = Field(default_factory=lambda: os.getenv("SESSION_NO_NEW_TRADE_AFTER", "15:05"))
    session_square_off_time: str = Field(default_factory=lambda: os.getenv("SESSION_SQUARE_OFF_TIME", "15:20"))
    session_market_close: str = Field(default_factory=lambda: os.getenv("SESSION_MARKET_CLOSE", "15:30"))
    session_post_market_end: str = Field(default_factory=lambda: os.getenv("SESSION_POST_MARKET_END", "16:00"))
    session_block_first_minutes: bool = Field(default_factory=lambda: _env_bool("SESSION_BLOCK_FIRST_MINUTES", True))
    session_block_expiry_last_30_min: bool = Field(
        default_factory=lambda: _env_bool("SESSION_BLOCK_EXPIRY_LAST_30_MIN", True)
    )
    session_allow_midday_trades: bool = Field(default_factory=lambda: _env_bool("SESSION_ALLOW_MIDDAY_TRADES", False))
    session_allow_late_session_trades: bool = Field(
        default_factory=lambda: _env_bool("SESSION_ALLOW_LATE_SESSION_TRADES", False)
    )

    @property
    def is_paper_mode(self) -> bool:
        return self.trading_mode == "PAPER"

    @property
    def has_dhan_credentials(self) -> bool:
        try:
            from app.services.dhan_auth_service import has_active_dhan_credentials

            return has_active_dhan_credentials(self)
        except Exception:
            return bool(self.dhan_client_id and self.dhan_access_token)

    @property
    def has_indstocks_credentials(self) -> bool:
        return bool(self.indstocks_access_token)

    @property
    def live_candle_timeframes_list(self) -> list[str]:
        return _env_list("LIVE_CANDLE_TIMEFRAMES", self.live_candle_timeframes)

    @property
    def live_feed_default_symbols_list(self) -> list[str]:
        return _env_list("LIVE_FEED_DEFAULT_SYMBOLS", self.live_feed_default_symbols)

    @property
    def market_backfill_symbols_list(self) -> list[str]:
        return _env_list("MARKET_BACKFILL_SYMBOLS", self.market_backfill_symbols)

    @property
    def signal_v2_entry_timeframes_list(self) -> list[str]:
        return _env_list("SIGNAL_V2_ENTRY_TIMEFRAMES", self.signal_v2_entry_timeframes)

    @property
    def reports_supported_formats_list(self) -> list[str]:
        return _env_list("REPORTS_SUPPORTED_FORMATS", self.reports_supported_formats)

    @property
    def session_gate_schedule(self) -> dict[str, str]:
        return {
            "pre_market_start": self.session_pre_market_start,
            "market_open": self.session_market_open,
            "first_trade_time": self.session_first_trade_time,
            "midday_start": self.session_midday_start,
            "midday_end": self.session_midday_end,
            "late_session_start": self.session_late_session_start,
            "no_new_trade_after": self.session_no_new_trade_after,
            "square_off_time": self.session_square_off_time,
            "market_close": self.session_market_close,
            "post_market_end": self.session_post_market_end,
        }

    @property
    def safety_status(self) -> dict[str, Any]:
        return {
            "trading_mode": self.trading_mode,
            "paper_trading_enabled": self.is_paper_mode,
            "live_orders_allowed": self.allow_live_orders,
            "dhan_order_placement_enabled": self.enable_dhan_order_placement,
            "live_order_status": "BLOCKED"
            if not (self.allow_live_orders and self.enable_dhan_order_placement)
            else "ENABLED",
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "app_name": self.app_name,
            "env": self.env,
            "trading_mode": self.trading_mode,
            "allow_live_orders": self.allow_live_orders,
            "enable_dhan_order_placement": self.enable_dhan_order_placement,
            "dhan_credentials_configured": self.has_dhan_credentials,
            "market_data_mode": self.market_data_mode,
            "dhan_data_enabled": self.dhan_data_enabled,
            "dhan_base_url": self.dhan_base_url,
            "dhan_rest_quota_guard_enabled": self.enable_dhan_rest_quota_guard,
            "dhan_rest_quota_per_minute": self.dhan_rest_quota_per_minute,
            "dhan_rest_min_gap_seconds": self.dhan_rest_min_gap_seconds,
            "dhan_rest_response_cache_seconds": self.dhan_rest_response_cache_seconds,
            "indstocks_enabled": self.indstocks_enabled,
            "indstocks_credentials_configured": self.has_indstocks_credentials,
            "indstocks_base_url": self.indstocks_base_url,
            "indstocks_use_as_secondary_data": self.indstocks_use_as_secondary_data,
            "indstocks_order_updates_ws_enabled": self.indstocks_enable_order_updates_ws,
            "indstocks_order_placement_enabled": self.indstocks_enable_order_placement,
            "database_url": _redact_url_credentials(self.database_url),
            "db_pool_size": self.db_pool_size,
            "db_max_overflow": self.db_max_overflow,
            "db_pool_timeout": self.db_pool_timeout,
            "db_pool_recycle": self.db_pool_recycle,
            "db_pool_pre_ping": self.db_pool_pre_ping,
            "database_pool_size": self.db_pool_size,
            "database_max_overflow": self.db_max_overflow,
            "database_pool_timeout": self.db_pool_timeout,
            "database_pool_recycle": self.db_pool_recycle,
            "max_trades_per_day": self.max_trades_per_day,
            "max_daily_loss": self.max_daily_loss,
            "max_qty_per_trade": self.max_qty_per_trade,
            "live_feed_enabled": self.enable_dhan_websocket,
            "live_feed_auto_subscribe": self.live_feed_auto_subscribe,
            "live_feed_default_symbols": self.live_feed_default_symbols_list,
            "live_tick_storage_enabled": self.store_live_ticks,
            "dhan_ws_auto_start": self.dhan_ws_auto_start,
            "live_candle_storage_enabled": self.store_live_candles,
            "live_candle_timeframes": self.live_candle_timeframes_list,
            "live_candle_max_history": self.live_candle_max_history,
            "live_market_stale_after_seconds": self.live_market_stale_after_seconds,
            "live_monitor_auto_start": self.live_monitor_auto_start,
            "feed_watchdog_enabled": self.enable_feed_watchdog,
            "feed_watchdog_interval_seconds": self.feed_watchdog_interval_seconds,
            "feed_watchdog_auto_recover": self.feed_watchdog_auto_recover,
            "startup_market_backfill_enabled": self.enable_startup_market_backfill,
            "market_backfill_symbols": self.market_backfill_symbols_list,
            "market_backfill_source_interval": self.market_backfill_source_interval,
            "test_tick_ingest_enabled": self.enable_test_tick_ingest,
            "data_quality_enabled": self.enable_data_quality_engine,
            "data_quality_rest_cross_check": self.data_quality_rest_cross_check,
            "data_quality_rest_cache_seconds": self.data_quality_rest_cache_seconds,
            "data_quality_max_rest_checks_per_minute": self.data_quality_max_rest_checks_per_minute,
            "data_quality_ltp_mismatch_percent": self.data_quality_ltp_mismatch_percent,
            "data_quality_rest_mismatch_blocks_paper": self.data_quality_rest_mismatch_blocks_paper,
            "data_quality_stale_after_seconds": self.data_quality_stale_after_seconds,
            "signal_engine_v2_enabled": self.enable_signal_engine_v2,
            "signal_v2_min_score": self.signal_v2_min_score,
            "signal_v2_primary_timeframe": self.signal_v2_primary_timeframe,
            "signal_v2_confirm_timeframe": self.signal_v2_confirm_timeframe,
            "signal_v2_entry_timeframes": self.signal_v2_entry_timeframes_list,
            "signal_v2_required_candles": {
                "1m": self.signal_v2_min_1m_candles,
                "3m": self.signal_v2_min_3m_candles,
                "5m": self.signal_v2_min_5m_candles,
                "15m": self.signal_v2_min_15m_candles,
            },
            "signal_v2_paper_min_score": self.signal_v2_paper_min_score,
            "signal_v2_session_gate_enabled": self.enable_signal_v2_session_gate,
            "signal_v2_session_gate_hard_block": self.signal_v2_session_gate_hard_block,
            "signal_v2_allow_analysis_when_session_blocked": self.signal_v2_allow_analysis_when_session_blocked,
            "live_paper_simulator_enabled": self.enable_live_paper_simulator,
            "live_paper_auto_start": self.live_paper_auto_start,
            "live_paper_underlying": self.live_paper_underlying,
            "live_paper_virtual_capital": self.live_paper_virtual_capital,
            "live_paper_max_open_trades": self.live_paper_max_open_trades,
            "live_paper_max_trades_per_day": self.live_paper_max_trades_per_day,
            "live_paper_min_signal_score": self.live_paper_min_signal_score,
            "live_paper_market_session_only": self.live_paper_market_session_only,
            "live_paper_use_indstocks_cross_check": self.live_paper_use_indstocks_cross_check,
            "live_paper_require_indstocks_confirmation": self.live_paper_require_indstocks_confirmation,
            "live_paper_session_gate_enabled": self.enable_live_paper_session_gate,
            "live_paper_block_entries_outside_session": self.live_paper_block_entries_outside_session,
            "live_paper_allow_exits_outside_entry_session": self.live_paper_allow_exits_outside_entry_session,
            "live_paper_allow_square_off_review": self.live_paper_allow_square_off_review,
            "strategy_evaluation_enabled": self.enable_strategy_evaluation,
            "strategy_eval_min_sample_size": self.strategy_eval_min_sample_size,
            "strategy_eval_lookback_days": self.strategy_eval_lookback_days,
            "market_flow_engine_enabled": self.enable_market_flow_engine,
            "market_flow_default_symbol": self.market_flow_default_symbol,
            "market_flow_use_live_candles": self.market_flow_use_live_candles,
            "market_flow_use_data_quality": self.market_flow_use_data_quality,
            "market_flow_use_indstocks_cross_check": self.market_flow_use_indstocks_cross_check,
            "market_flow_require_indstocks": self.market_flow_require_indstocks,
            "market_flow_cache_seconds": self.market_flow_cache_seconds,
            "option_chain_snapshots_enabled": self.enable_option_chain_snapshots,
            "option_chain_snapshot_auto_capture": self.option_chain_snapshot_auto_capture,
            "option_chain_snapshot_default_symbol": self.option_chain_snapshot_default_symbol,
            "option_chain_snapshot_interval_seconds": self.option_chain_snapshot_interval_seconds,
            "option_chain_snapshot_retention_days": self.option_chain_snapshot_retention_days,
            "signal_v2_market_flow_gate_enabled": self.enable_signal_v2_market_flow_gate,
            "signal_v2_use_market_flow": self.signal_v2_use_market_flow,
            "signal_v2_require_market_flow": self.signal_v2_require_market_flow,
            "signal_v2_market_flow_min_score": self.signal_v2_market_flow_min_score,
            "signal_v2_require_oi_change": self.signal_v2_require_oi_change,
            "participant_flow_engine_enabled": self.enable_participant_flow_engine,
            "participant_flow_data_mode": self.participant_flow_data_mode,
            "participant_flow_allow_web_fetch": self.participant_flow_allow_web_fetch,
            "participant_flow_default_symbol": self.participant_flow_default_symbol,
            "participant_flow_lookback_days": self.participant_flow_lookback_days,
            "participant_flow_sample_data_enabled": self.enable_participant_flow_sample_data,
            "sector_breadth_engine_enabled": self.enable_sector_breadth_engine,
            "sector_breadth_default_index": self.sector_breadth_default_index,
            "sector_breadth_cache_seconds": self.sector_breadth_cache_seconds,
            "sector_breadth_use_dhan": self.sector_breadth_use_dhan,
            "sector_breadth_use_indstocks_cross_check": self.sector_breadth_use_indstocks_cross_check,
            "sector_breadth_require_indstocks": self.sector_breadth_require_indstocks,
            "sector_breadth_heavyweight_mode": self.sector_breadth_heavyweight_mode,
            "sector_breadth_allow_partial_data": self.sector_breadth_allow_partial_data,
            "reporting_engine_enabled": self.enable_reporting_engine,
            "reports_default_lookback_days": self.reports_default_lookback_days,
            "reports_supported_formats": self.reports_supported_formats_list,
            "reports_store_snapshots": self.reports_store_snapshots,
            "ai_analyst_enabled": self.enable_ai_analyst,
            "ai_analyst_configured": bool(self.gemini_api_key),
            "ai_analyst_model": self.gemini_model_name,
            "session_gate_enabled": self.enable_session_gate,
            "session_gate_timezone": self.session_gate_timezone,
            "session_gate_schedule": self.session_gate_schedule,
            "session_block_first_minutes": self.session_block_first_minutes,
            "session_block_expiry_last_30_min": self.session_block_expiry_last_30_min,
            "session_allow_midday_trades": self.session_allow_midday_trades,
            "session_allow_late_session_trades": self.session_allow_late_session_trades,
        }


settings = Settings()
