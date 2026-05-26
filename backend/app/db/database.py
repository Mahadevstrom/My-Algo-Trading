from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


engine_kwargs = {"pool_pre_ping": settings.db_pool_pre_ping}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        "timeout": 30,
    }
else:
    engine_kwargs.update(
        {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
        }
    )

engine = create_engine(settings.database_url, **engine_kwargs)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models.audit_log import AuditLog
    from app.models.backtest_run import BacktestRun
    from app.models.backtest_trade import BacktestTrade
    from app.models.candle import Candle
    from app.models.instrument import InstrumentMaster
    from app.models.live_candle import LiveCandleRecord
    from app.models.live_tick import LiveTick
    from app.models.option_chain_snapshot import OptionChainSnapshot, OptionChainStrikeSnapshot
    from app.models.participant_flow import ParticipantFlowRecord
    from app.models.risk_state import RiskState
    from app.models.signal import SignalRecord
    from app.models.strategy import CustomStrategy
    from app.models.trade import PaperTrade, PaperOptionCombo
    from app.agent_evolution.models import AgentEvolutionRecommendation
    from app.engine.specialist.models import LabelRecord, SpecialistEngineLog

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()
    _migrate_postgresql_columns()


def _migrate_sqlite_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if not inspector.has_table("paper_trades"):
        return

    inspected_columns = {column["name"]: column for column in inspector.get_columns("paper_trades")}
    existing_columns = set(inspected_columns)
    columns_to_add = {
        "pnl_percent": "FLOAT",
        "result": "VARCHAR(20) DEFAULT 'OPEN'",
        "exit_reason": "VARCHAR(30)",
        "holding_minutes": "FLOAT",
        "unrealized_pnl": "FLOAT",
        "current_price": "FLOAT",
        "signal_id": "INTEGER",
        "underlying": "VARCHAR(50)",
        "selected_strike": "FLOAT",
        "strategy_score": "FLOAT",
        "data_confidence": "FLOAT",
        "final_confidence": "FLOAT",
        "chain_bias": "VARCHAR(20)",
        "signal_type": "VARCHAR(20)",
        "combo_id": "INTEGER",
        "filter_states_json": "TEXT",
        "confidence_score_at_entry": "FLOAT",
        "regime_at_entry": "VARCHAR(50)",
        "session_window_at_entry": "VARCHAR(50)",
        "oi_direction_at_entry": "VARCHAR(50)",
        "market_flow_score_at_entry": "FLOAT",
        "pcr_at_entry": "FLOAT",
        "spread_pct_at_entry": "FLOAT",
        "filters_passed_count": "INTEGER",
        "birth_cert_version": "VARCHAR(20)",
    }
    with engine.begin() as connection:
        for column_name, column_type in columns_to_add.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE paper_trades ADD COLUMN {column_name} {column_type}"))


def _migrate_postgresql_columns() -> None:
    if not settings.database_url.startswith("postgresql"):
        return

    inspector = inspect(engine)
    if not inspector.has_table("paper_trades"):
        return

    inspected_columns = {column["name"]: column for column in inspector.get_columns("paper_trades")}
    existing_columns = set(inspected_columns)
    columns_to_add = {
        "pnl_percent": "DOUBLE PRECISION",
        "result": "VARCHAR(20) DEFAULT 'OPEN'",
        "exit_reason": "VARCHAR(30)",
        "holding_minutes": "DOUBLE PRECISION",
        "unrealized_pnl": "DOUBLE PRECISION",
        "current_price": "DOUBLE PRECISION",
        "signal_id": "INTEGER",
        "underlying": "VARCHAR(50)",
        "selected_strike": "DOUBLE PRECISION",
        "strategy_score": "DOUBLE PRECISION",
        "data_confidence": "DOUBLE PRECISION",
        "final_confidence": "DOUBLE PRECISION",
        "chain_bias": "VARCHAR(20)",
        "signal_type": "VARCHAR(20)",
        "combo_id": "INTEGER",
        "filter_states_json": "TEXT",
        "confidence_score_at_entry": "DOUBLE PRECISION",
        "regime_at_entry": "VARCHAR(50)",
        "session_window_at_entry": "VARCHAR(50)",
        "oi_direction_at_entry": "VARCHAR(50)",
        "market_flow_score_at_entry": "DOUBLE PRECISION",
        "pcr_at_entry": "DOUBLE PRECISION",
        "spread_pct_at_entry": "DOUBLE PRECISION",
        "filters_passed_count": "INTEGER",
        "birth_cert_version": "VARCHAR(20)",
    }

    with engine.begin() as connection:
        status_column = inspected_columns.get("status")
        status_type = str(status_column.get("type", "")).upper() if status_column else ""
        if "VARCHAR(30)" not in status_type and "CHARACTER VARYING(30)" not in status_type:
            connection.execute(text("ALTER TABLE paper_trades ALTER COLUMN status TYPE VARCHAR(30)"))
        for column_name, column_type in columns_to_add.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE paper_trades ADD COLUMN {column_name} {column_type}"))
        birth_cert_column = inspected_columns.get("birth_cert_version")
        if birth_cert_column and birth_cert_column.get("default") is not None:
            connection.execute(text("ALTER TABLE paper_trades ALTER COLUMN birth_cert_version DROP DEFAULT"))
