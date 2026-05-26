from contextlib import asynccontextmanager
from typing import AsyncIterator
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Size-based log rotation setup
BACKEND_DIR = Path(__file__).resolve().parents[1]
LOGS_DIR = BACKEND_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

debug_handler = RotatingFileHandler(
    LOGS_DIR / "debug.log",
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=5,
    encoding="utf-8"
)
debug_handler.setLevel(logging.DEBUG)

error_handler = RotatingFileHandler(
    LOGS_DIR / "error.log",
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=5,
    encoding="utf-8"
)
error_handler.setLevel(logging.WARNING)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d) - %(message)s"
)
debug_handler.setFormatter(formatter)
error_handler.setFormatter(formatter)

# Configure Root Logger and key standard loggers
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(debug_handler)
root_logger.addHandler(error_handler)

for logger_name in ("fastapi", "uvicorn", "uvicorn.error", "uvicorn.access"):
    logger_instance = logging.getLogger(logger_name)
    logger_instance.addHandler(debug_handler)
    logger_instance.addHandler(error_handler)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_accuracy import router as accuracy_router
from app.api.routes_audit import router as audit_router
from app.api.routes_backtest import router as backtest_router, walk_forward_router
from app.api.routes_broker import router as broker_router
from app.api.routes_data_quality import router as data_quality_router
from app.api.routes_dhan_instruments import router as dhan_instruments_router
from app.api.routes_health import router as health_router
from app.api.routes_historical import router as historical_router
from app.api.routes_analytics import router as analytics_router
from app.api.routes_instruments import router as instruments_router
from app.api.routes_indstocks import router as indstocks_router
from app.api.routes_live_feed import router as live_feed_router
from app.api.routes_live_monitor import router as live_monitor_router
from app.api.routes_live_paper import router as live_paper_router
from app.api.routes_market import router as market_router
from app.api.routes_market_flow import router as market_flow_router
from app.api.routes_nse_data import router as nse_data_router
from app.api.routes_option_chain import router as option_chain_router
from app.api.routes_option_chain_snapshots import router as option_chain_snapshots_router
from app.api.routes_paper import router as paper_router
from app.api.routes_participant_flow import router as participant_flow_router
from app.api.routes_risk import router as risk_router
from app.api.routes_reports import router as reports_router
from app.api.routes_replay import router as replay_router
from app.api.routes_settings import router as settings_router
from app.api.routes_sector_breadth import router as sector_breadth_router
from app.api.routes_session_gate import router as session_gate_router
from app.api.routes_signals import router as signals_router
from app.api.routes_signals_v2 import router as signals_v2_router
from app.api.routes_strategy_evaluation import router as strategy_evaluation_router
from app.api.routes_strategies import router as strategies_router
from app.api.routes_trade_journal import router as trade_journal_router
from app.api.routes_ai_analyst import router as ai_analyst_router
from app.engine.specialist.routes import router as specialist_router
from app.config import settings
from app.db.database import init_db
from app.services.live_feed_service import get_live_feed_service
from app.services.live_market_monitor_service import get_live_market_monitor_service
from app.services.live_paper_simulator_service import get_live_paper_simulator_service
from app.agent_evolution.routes import router as agent_evolution_router
from app.agent_evolution.scheduler import get_agent_evolution_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    await get_live_feed_service().auto_start_if_configured()
    await get_live_market_monitor_service().auto_start_if_configured()
    await get_live_paper_simulator_service().auto_start_if_configured()
    
    # Start Option Chain Snapshot Background Scheduler
    from app.services.option_chain_snapshot_service import get_option_chain_snapshot_service
    get_option_chain_snapshot_service().start_scheduler()
    
    # Start Agent Evolution Scheduler
    get_agent_evolution_scheduler().start()
    
    try:
        yield
    finally:
        # Shutdown Agent Evolution Scheduler
        get_agent_evolution_scheduler().stop()
        
        # Shutdown Option Chain Snapshot Background Scheduler
        await get_option_chain_snapshot_service().shutdown_scheduler()
        
        await get_live_paper_simulator_service().shutdown()
        await get_live_market_monitor_service().shutdown()
        await get_live_feed_service().shutdown()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Paper-only Indian F&O trading terminal backend.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(settings_router)
app.include_router(accuracy_router)
app.include_router(audit_router)
app.include_router(backtest_router)
app.include_router(walk_forward_router)
app.include_router(broker_router)
app.include_router(data_quality_router)
app.include_router(signals_router)
app.include_router(signals_v2_router)
app.include_router(strategy_evaluation_router)
app.include_router(paper_router)
app.include_router(risk_router)
app.include_router(instruments_router)
app.include_router(dhan_instruments_router)
app.include_router(indstocks_router)
app.include_router(market_router)
app.include_router(market_flow_router)
app.include_router(nse_data_router)
app.include_router(option_chain_router)
app.include_router(option_chain_snapshots_router)
app.include_router(participant_flow_router)
app.include_router(sector_breadth_router)
app.include_router(session_gate_router)
app.include_router(reports_router)
app.include_router(ai_analyst_router)
app.include_router(replay_router)
app.include_router(historical_router)
app.include_router(live_feed_router)
app.include_router(live_monitor_router)
app.include_router(live_paper_router)
app.include_router(strategies_router)
app.include_router(trade_journal_router)
app.include_router(analytics_router)
app.include_router(agent_evolution_router)
app.include_router(specialist_router, prefix="/api/engine")


@app.get("/")
def root() -> dict:
    return {
        "app_name": settings.app_name,
        "mode": settings.trading_mode,
        "safety_status": settings.safety_status,
    }
