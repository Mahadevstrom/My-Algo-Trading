from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from datetime import datetime

from app.services.ai_analyst_service import ai_analyst_service
from app.services.market_flow_service import get_market_flow_service
from app.services.option_chain_snapshot_service import get_option_chain_snapshot_service
from app.services.participant_flow_service import get_participant_flow_service
from app.config import settings
from app.db.database import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/ai", tags=["AI Analyst"])

@router.get("/status")
async def get_ai_status():
    openai_is_real = bool(settings.openai_api_key) and not (settings.openai_base_url and "11434" in settings.openai_base_url)
    return {
        "enabled": settings.enable_ai_analyst,
        "configured": bool(settings.gemini_api_key) or bool(settings.openai_api_key) or bool(settings.ollama_base_url),
        "model": settings.gemini_model_name,
        "default_provider": settings.ai_provider,
        "is_ready": ai_analyst_service.is_ready(),
        "providers": {
            "gemini": {
                "configured": bool(settings.gemini_api_key),
                "model": settings.gemini_model_name
            },
            "openai": {
                "configured": openai_is_real,
                "model": settings.openai_model_name
            },
            "ollama": {
                "configured": bool(settings.ollama_base_url),
                "model": settings.ollama_model_name,
                "url": settings.ollama_base_url
            }
        }
    }

@router.get("/market-structure")
async def analyze_market_structure(db: Session = Depends(get_db), provider: str = None):
    if not ai_analyst_service.is_ready():
        raise HTTPException(status_code=503, detail="AI Analyst service is not available or configured.")

    symbol = settings.market_flow_default_symbol
    
    # Gather Market Flow Data
    try:
        market_flow = await get_market_flow_service().summary(db, symbol)
    except Exception as e:
        market_flow = {"error": str(e)}
        
    # Gather OI Data
    from app.schemas.option_chain_snapshot import OptionChainSnapshotSummary
    snapshots = get_option_chain_snapshot_service().get_snapshot_history(db, symbol, None, limit=1)
    oi_data = {"snapshot": OptionChainSnapshotSummary.model_validate(snapshots[0]).model_dump(mode="json") if snapshots else "No recent snapshots"}

    # Gather Participant Flow Data
    participant_data = get_participant_flow_service().context(db, symbol)

    result = await ai_analyst_service.analyze_market_structure(
        market_flow_data=market_flow,
        oi_data=oi_data,
        fii_dii_data=participant_data,
        provider=provider
    )
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
        
    return result

@router.get("/post-market-report")
async def get_post_market_report(db: Session = Depends(get_db), provider: str = None):
    if not ai_analyst_service.is_ready():
        raise HTTPException(status_code=503, detail="AI Analyst service is not available or configured.")

    from app.services.live_paper_simulator_service import get_live_paper_simulator_service
    from app.engine.paper_engine import PaperEngine
    
    paper_simulator_status = await get_live_paper_simulator_service().status(db)
    
    # Get all trades
    trades = PaperEngine().list_trades(db)
    today_trades = [t for t in trades if t.entry_time and t.entry_time.date() == datetime.utcnow().date()]
    trade_dumps = []
    for t in today_trades:
        trade_dumps.append({
            "id": t.id,
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl": t.pnl,
            "pnl_percent": t.pnl_percent,
            "result": t.result,
            "exit_reason": t.exit_reason
        })
    
    performance_metrics = {
        "total_pnl": paper_simulator_status.get("realized_pnl_today", 0),
        "total_trades": paper_simulator_status.get("closed_today_count", 0),
        "win_rate": PaperEngine().performance(db).win_rate,
        "max_drawdown": "N/A"
    }

    symbol = settings.live_paper_underlying
    try:
        market_flow = await get_market_flow_service().summary(db, symbol)
    except Exception as e:
        market_flow = {"error": str(e)}
        
    participant_data = get_participant_flow_service().context(db, symbol)
    
    market_context = {
        "symbol": symbol,
        "market_flow_state": market_flow,
        "participant_bias": participant_data.get("participant_bias", "UNKNOWN")
    }

    result = await ai_analyst_service.generate_post_market_report(
        performance_metrics=performance_metrics,
        trades=trade_dumps,
        market_context=market_context,
        provider=provider
    )
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
        
    return result
