import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.setup.models import SetupDefinition
from app.engine.setup.setup_types import SetupName


def seed_core_setups(db: Session) -> int:
    created = 0
    for definition in _core_setup_definitions():
        existing = db.scalar(select(SetupDefinition).where(SetupDefinition.setup_name == definition["setup_name"]))
        if existing:
            continue
        db.add(SetupDefinition(**definition))
        created += 1
    if created:
        db.commit()
    return created


def _json(value) -> str:
    return json.dumps(value)


def _condition(engine: str, field: str, operator: str, value, description: str) -> dict:
    return {
        "engine": engine,
        "field": field,
        "operator": operator,
        "value": value,
        "description": description,
    }


def _core_setup_definitions() -> list[dict]:
    return [
        {
            "setup_name": SetupName.PE_BREAKDOWN_CONTINUATION,
            "display_name": "PE Breakdown Continuation",
            "description": "Market breaks below support with bearish OI confirmation.",
            "direction": "PE",
            "required_conditions_json": _json(
                [
                    _condition("market_structure_engine", "direction", "eq", "BEARISH", "Market structure must confirm bearish trend"),
                    _condition("option_chain_engine", "direction", "eq", "BEARISH", "OI must show PE strength or bearish bias"),
                    _condition("context", "data_quality_status", "in", ["CLEAN", "UNKNOWN"], "Data must not be STALE"),
                ]
            ),
            "supporting_conditions_json": _json(
                [
                    _condition(
                        "market_structure_engine",
                        "verdict",
                        "in",
                        ["BEARISH_TREND", "BREAKDOWN_CONFIRMED", "BELOW_VWAP_WEAK"],
                        "Price below key levels confirms breakdown",
                    ),
                    _condition("option_chain_engine", "score", "gte", 60, "Option chain score shows conviction"),
                    _condition(
                        "context",
                        "context_type",
                        "not_in",
                        ["EXPIRY_DAY_AFTERNOON", "STALE_DATA_DAY"],
                        "Avoid dangerous time windows",
                    ),
                ]
            ),
            "min_supporting_required": 2,
            "valid_contexts_json": _json([]),
            "blocked_contexts_json": _json(["EXPIRY_DAY_AFTERNOON", "STALE_DATA_DAY", "RANGING_CHOPPY"]),
            "context_modifiers_json": _json(
                {"GAP_DOWN_CONTINUATION": 0.08, "BEARISH_TREND": 0.05, "HIGH_VIX_DAY": -0.05, "EXPIRY_DAY_MORNING": -0.03}
            ),
            "min_confidence": 0.62,
            "is_active": True,
            "version": 1,
        },
        {
            "setup_name": SetupName.CE_BREAKOUT_CONTINUATION,
            "display_name": "CE Breakout Continuation",
            "description": "Market breaks above resistance with bullish OI confirmation.",
            "direction": "CE",
            "required_conditions_json": _json(
                [
                    _condition("market_structure_engine", "direction", "eq", "BULLISH", "Market structure must confirm bullish trend"),
                    _condition("option_chain_engine", "direction", "eq", "BULLISH", "OI must show CE strength or bullish bias"),
                    _condition("context", "data_quality_status", "in", ["CLEAN", "UNKNOWN"], "Data must not be STALE"),
                ]
            ),
            "supporting_conditions_json": _json(
                [
                    _condition(
                        "market_structure_engine",
                        "verdict",
                        "in",
                        ["BULLISH_TREND", "BREAKOUT_CONFIRMED", "ABOVE_VWAP_WEAK"],
                        "Price above key levels confirms breakout",
                    ),
                    _condition("option_chain_engine", "score", "lte", 40, "Option chain score shows CE conviction"),
                    _condition(
                        "context",
                        "context_type",
                        "not_in",
                        ["EXPIRY_DAY_AFTERNOON", "STALE_DATA_DAY"],
                        "Avoid dangerous time windows",
                    ),
                ]
            ),
            "min_supporting_required": 2,
            "valid_contexts_json": _json([]),
            "blocked_contexts_json": _json(["EXPIRY_DAY_AFTERNOON", "STALE_DATA_DAY"]),
            "context_modifiers_json": _json({"GAP_UP_CONTINUATION": 0.08, "HIGH_VIX_DAY": -0.05}),
            "min_confidence": 0.62,
            "is_active": True,
            "version": 1,
        },
        {
            "setup_name": SetupName.PE_VWAP_REJECTION,
            "display_name": "PE VWAP Rejection",
            "description": "Price rejected at VWAP from above with bearish OI.",
            "direction": "PE",
            "required_conditions_json": _json(
                [
                    _condition("market_structure_engine", "verdict", "eq", "VWAP_REJECTION", "Must have confirmed VWAP rejection"),
                    _condition("option_chain_engine", "direction", "in", ["BEARISH", "NEUTRAL"], "OI must not be bullish"),
                ]
            ),
            "supporting_conditions_json": _json(
                [
                    _condition("market_structure_engine", "score", "lte", 45, "Market structure score is bearish enough"),
                    _condition("option_chain_engine", "verdict", "in", ["PE_STRONG", "NEUTRAL"], "Option chain is PE-supportive or neutral"),
                    _condition(
                        "context",
                        "context_type",
                        "in",
                        ["NORMAL_TRADING_DAY", "TRENDING_MORNING", "GAP_DOWN_CONTINUATION"],
                        "Context supports VWAP rejection scalp",
                    ),
                ]
            ),
            "min_supporting_required": 1,
            "valid_contexts_json": _json([]),
            "blocked_contexts_json": _json(["EXPIRY_DAY_AFTERNOON", "STALE_DATA_DAY", "HIGH_VIX_DAY"]),
            "context_modifiers_json": _json({}),
            "min_confidence": 0.60,
            "is_active": True,
            "version": 1,
        },
        {
            "setup_name": SetupName.CE_VWAP_RECLAIM,
            "display_name": "CE VWAP Reclaim",
            "description": "Price reclaimed VWAP from below with bullish OI.",
            "direction": "CE",
            "required_conditions_json": _json(
                [
                    _condition("market_structure_engine", "verdict", "eq", "VWAP_RECLAIM", "Must have confirmed VWAP reclaim"),
                    _condition("option_chain_engine", "direction", "in", ["BULLISH", "NEUTRAL"], "OI must not be bearish"),
                ]
            ),
            "supporting_conditions_json": _json(
                [
                    _condition("market_structure_engine", "score", "gte", 55, "Market structure score is bullish enough"),
                    _condition("option_chain_engine", "verdict", "in", ["CE_STRONG", "NEUTRAL"], "Option chain is CE-supportive or neutral"),
                    _condition(
                        "context",
                        "context_type",
                        "in",
                        ["NORMAL_TRADING_DAY", "TRENDING_MORNING", "GAP_UP_CONTINUATION"],
                        "Context supports VWAP reclaim scalp",
                    ),
                ]
            ),
            "min_supporting_required": 1,
            "valid_contexts_json": _json([]),
            "blocked_contexts_json": _json(["EXPIRY_DAY_AFTERNOON", "STALE_DATA_DAY"]),
            "context_modifiers_json": _json({}),
            "min_confidence": 0.60,
            "is_active": True,
            "version": 1,
        },
        {
            "setup_name": SetupName.PE_EXPIRY_MORNING_SCALP,
            "display_name": "PE Expiry Morning Scalp",
            "description": "Short-term PE scalp on expiry morning when premium still has value.",
            "direction": "PE",
            "required_conditions_json": _json(
                [
                    _condition("context", "context_type", "eq", "EXPIRY_DAY_MORNING", "Only valid on expiry morning"),
                    _condition("option_chain_engine", "verdict", "in", ["PE_STRONG", "NEUTRAL"], "OI must support PE"),
                    _condition("option_chain_engine", "verdict", "neq", "PREMIUM_WEAK", "Premium must have enough value to trade"),
                ]
            ),
            "supporting_conditions_json": _json(
                [
                    _condition("market_structure_engine", "direction", "eq", "BEARISH", "Market structure supports PE scalp"),
                    _condition("option_chain_engine", "score", "gte", 55, "Option chain score is strong enough"),
                ]
            ),
            "min_supporting_required": 1,
            "valid_contexts_json": _json(["EXPIRY_DAY_MORNING"]),
            "blocked_contexts_json": _json(["EXPIRY_DAY_AFTERNOON", "STALE_DATA_DAY", "HIGH_VIX_DAY"]),
            "context_modifiers_json": _json({}),
            "min_confidence": 0.70,
            "is_active": True,
            "version": 1,
        },
    ]
