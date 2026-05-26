import asyncio
from datetime import datetime, time
from zoneinfo import ZoneInfo
from app.db.database import SessionLocal
from app.config import settings
from app.audit.audit_logger import AuditLogger
from app.agent_evolution.analyzer import run_analysis
from app.agent_evolution.recommendation_engine import generate_recommendations
from app.services.ai_analyst_service import ai_analyst_service

IST = ZoneInfo("Asia/Kolkata")


def _parse_run_time_ist(value: str) -> time:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        return time(int(hour_text), int(minute_text))
    except (AttributeError, TypeError, ValueError):
        return time(18, 30)


async def run_nightly_evolution():
    db = SessionLocal()
    try:
        if not settings.enable_agent_evolution_engine:
            return
            
        print("Starting nightly Agent Evolution analysis run...")
        report = run_analysis(db, settings.agent_evolution_lookback_days, settings.agent_evolution_min_trades)
        
        if report.get("status") == "INSUFFICIENT_DATA":
            AuditLogger().log(
                db,
                event_type="AGENT_EVOLUTION_NIGHTLY_SKIPPED",
                severity="INFO",
                source="AGENT_EVOLUTION",
                message="Nightly Agent Evolution analysis skipped due to insufficient trade data.",
                payload={"status": "INSUFFICIENT_DATA"}
            )
            return
            
        recs = generate_recommendations(
            db,
            report,
            report["run_id"],
            settings.agent_evolution_max_recs_per_run
        )
        synthesis = None
        if ai_analyst_service.is_ready():
            synthesis = await ai_analyst_service.synthesize_agent_evolution(
                report,
                [_recommendation_payload(rec) for rec in recs],
            )
        
        AuditLogger().log(
            db,
            event_type="AGENT_EVOLUTION_NIGHTLY_SUCCESS",
            severity="INFO",
            source="AGENT_EVOLUTION",
            message=f"Nightly Agent Evolution analysis completed. Generated {len(recs)} recommendations.",
            payload={
                "run_id": report["run_id"],
                "recs_generated": len(recs),
                "ai_provider": ai_analyst_service.default_provider if synthesis is not None else None,
                "ai_model": settings.gemini_model_name if synthesis is not None else None,
                "nightly_synthesis": synthesis,
            }
        )
        print("Nightly Agent Evolution analysis run complete.")
    except Exception as e:
        print(f"Error in nightly agent evolution: {e}")
        try:
            AuditLogger().log(
                db,
                event_type="AGENT_EVOLUTION_NIGHTLY_FAILED",
                severity="WARNING",
                source="AGENT_EVOLUTION",
                message=f"Nightly Agent Evolution analysis failed: {str(e)}",
                payload={"error": str(e)}
            )
        except Exception:
            pass
    finally:
        db.close()

class AgentEvolutionScheduler:
    def __init__(self):
        self._task = None
        self._running = False
        
    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._scheduler_loop())
            print("Agent Evolution background scheduler started.")
            
    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            print("Agent Evolution background scheduler stopped.")
            
    async def _scheduler_loop(self) -> None:
        initial_now_ist = datetime.now(IST)
        initial_run_time = _parse_run_time_ist(settings.agent_evolution_run_time_ist)
        last_run_date = (
            initial_now_ist.date()
            if initial_now_ist.time().replace(second=0, microsecond=0) >= initial_run_time
            else None
        )
        while self._running:
            try:
                if not settings.enable_agent_evolution_engine or not settings.agent_evolution_nightly_run:
                    await asyncio.sleep(60)
                    continue
                    
                now_ist = datetime.now(IST)
                run_time = _parse_run_time_ist(settings.agent_evolution_run_time_ist)
                
                if (
                    now_ist.time().replace(second=0, microsecond=0) >= run_time
                    and last_run_date != now_ist.date()
                ):
                    last_run_date = now_ist.date()
                    await run_nightly_evolution()
                    
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in agent evolution scheduler loop: {e}")
                await asyncio.sleep(10)

_scheduler = AgentEvolutionScheduler()

def get_agent_evolution_scheduler() -> AgentEvolutionScheduler:
    return _scheduler


def _recommendation_payload(rec) -> dict:
    return {
        "id": rec.id,
        "recommendation_type": rec.recommendation_type,
        "affected_module": rec.affected_module,
        "issue_detected": rec.issue_detected,
        "suggested_change": rec.suggested_change,
        "risk_level": rec.risk_level,
        "confidence": rec.confidence,
        "status": rec.status,
        "run_id": rec.run_id,
    }
