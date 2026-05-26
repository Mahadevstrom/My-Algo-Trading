import logging
import json
from typing import Any, Dict
from google import genai
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

class AiAnalystService:
    def __init__(self):
        self.enabled = settings.enable_ai_analyst
        self.default_provider = settings.ai_provider
        
        self._gemini_client = None
        self._gemini_model = None
        self._openai_client = None
        self._ollama_client = None
        
        if self.enabled:
            # Initialize Gemini
            if settings.gemini_api_key:
                try:
                    self._gemini_client = genai.Client(api_key=settings.gemini_api_key)
                    self._gemini_model = "gemini-2.5-flash-preview-05-20"
                    logger.info(f"AI Analyst registered Gemini model: {self._gemini_model}")
                except Exception as e:
                    logger.error(f"Failed to initialize Gemini: {e}")
                    
            # Initialize OpenAI (or Ollama if base URL is provided)
            if settings.openai_api_key:
                try:
                    from openai import AsyncOpenAI
                    kwargs = {"api_key": settings.openai_api_key, "timeout": 30.0, "max_retries": 0}
                    if settings.openai_base_url:
                        kwargs["base_url"] = settings.openai_base_url
                    self._openai_client = AsyncOpenAI(**kwargs)
                    logger.info(f"AI Analyst registered OpenAI model: {settings.openai_model_name}")
                except Exception as e:
                    logger.error(f"Failed to initialize OpenAI: {e}")

            # Initialize Ollama
            if settings.ollama_base_url:
                try:
                    from openai import AsyncOpenAI
                    self._ollama_client = AsyncOpenAI(
                        api_key="ollama",
                        base_url=settings.ollama_base_url,
                        timeout=75.0,
                        max_retries=0,
                    )
                    logger.info(f"AI Analyst registered Ollama model: {settings.ollama_model_name} at {settings.ollama_base_url}")
                except Exception as e:
                    logger.error(f"Failed to initialize Ollama: {e}")

    def is_ready(self) -> bool:
        if not self.enabled:
            return False
        return (
            self._gemini_client is not None or 
            self._openai_client is not None or 
            self._ollama_client is not None
        )

    async def _get_json_response(self, prompt: str, provider: str | None = None) -> Dict[str, Any]:
        target_provider = provider or self.default_provider
        
        if target_provider == "gemini":
            if not self._gemini_client:
                return {"error": "Gemini is not configured. Missing GEMINI_API_KEY."}
            try:
                response = self._gemini_client.models.generate_content(
                    model=self._gemini_model,
                    contents=prompt
                )
                return json.loads(response.text)
            except Exception as e:
                logger.error(f"Error generating Gemini response: {e}")
                return {"error": f"Failed to generate Gemini response: {str(e)}"}
                
        elif target_provider == "openai":
            if not self._openai_client:
                return {"error": "OpenAI is not configured. Missing OPENAI_API_KEY."}
            try:
                return await self._get_openai_response(prompt)
            except Exception as e:
                logger.error(f"Error generating OpenAI response: {e}")
                return {"error": f"Failed to generate OpenAI response: {str(e)}"}
                
        elif target_provider == "ollama":
            if not self._ollama_client:
                return {"error": "Ollama is not configured. Check OLLAMA_BASE_URL setting."}
            try:
                response = await self._ollama_client.chat.completions.create(
                    model=settings.ollama_model_name,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=900,
                )
                return json.loads(response.choices[0].message.content)
            except Exception as e:
                logger.error(f"Error generating Ollama response: {e}")
                return {"error": f"Failed to generate Ollama response: {str(e)}"}
                
        else:
            return {"error": f"Unknown AI provider: {target_provider}"}

    async def _get_openai_response(self, prompt: str) -> Dict[str, Any]:
        base_url = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.openai_model_name,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 900,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)

        if response.status_code >= 400:
            return {"error": self._format_openai_error(response)}

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)

    def _format_openai_error(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
            error = payload.get("error") or {}
            message = error.get("message")
            code = error.get("code")
            if message:
                suffix = f" ({code})" if code else ""
                return f"OpenAI API error {response.status_code}: {message}{suffix}"
        except Exception:
            pass
        return f"OpenAI API error {response.status_code}: {response.text[:300]}"

    async def analyze_market_structure(self, 
                                       market_flow_data: dict, 
                                       oi_data: dict, 
                                       fii_dii_data: dict,
                                       provider: str | None = None) -> dict:
        """
        Interprets real-time Market Flow trap metrics, OI change biases, and institutional positioning.
        """
        compact_market_flow = self._compact_market_flow(market_flow_data)
        compact_oi = self._compact_oi_data(oi_data)
        compact_participant = self._compact_participant_flow(fii_dii_data)

        prompt = f"""
        You are an elite quantitative trading analyst for an Indian trading desk.
        Analyze the current market structure based on the provided data and return a JSON object.
        
        Data context:
        - Market Flow: {json.dumps(compact_market_flow)}
        - Options OI Bias: {json.dumps(compact_oi)}
        - FII/DII Positioning: {json.dumps(compact_participant)}
        
        Required JSON Schema:
        {{
            "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL" | "CHOPPY",
            "confidence_score": 1-100,
            "path_of_least_resistance": "Explanation of where the market wants to go",
            "traps_identified": [
                {{"type": "CALL_TRAP"|"PUT_TRAP", "strike": 0, "severity": "HIGH"|"MEDIUM"|"LOW", "description": "Details"}}
            ],
            "institutional_bias": "Explanation of what FII/DII data suggests",
            "key_levels": {{"support": [0], "resistance": [0]}},
            "executive_summary": "A 2-3 sentence punchy summary for the trader to read right now."
        }}
        """
        return await self._get_json_response(prompt, provider=provider)

    def _compact_market_flow(self, data: dict) -> dict:
        option_flow = data.get("option_money_flow") or {}
        chain = data.get("chain_summary") or {}
        trap = data.get("trap_detection") or {}
        return {
            "symbol": data.get("symbol") or data.get("underlying"),
            "spot": data.get("spot") or chain.get("spot_price"),
            "atm_strike": data.get("atm_strike") or chain.get("atm_strike"),
            "market_flow_bias": data.get("market_flow_bias") or data.get("bias"),
            "option_flow_bias": data.get("option_flow_bias"),
            "flow_change_bias": option_flow.get("flow_change_bias") or data.get("flow_change_bias"),
            "flow_score": data.get("flow_score"),
            "flow_strength": data.get("flow_strength"),
            "confidence": data.get("confidence"),
            "pcr_oi": data.get("pcr_oi") or chain.get("pcr_oi"),
            "pcr_volume": data.get("pcr_volume") or chain.get("pcr_volume"),
            "support": data.get("support_zone") or chain.get("support_strike"),
            "resistance": data.get("resistance_zone") or chain.get("resistance_strike"),
            "trap_risk": trap.get("trap_risk") or data.get("trap_risk"),
            "trap_type": trap.get("trap_type") or data.get("trap_type"),
            "trap_reason": trap.get("trap_reason") or data.get("trap_reason"),
            "reasons": self._take(data.get("reasons"), 6),
            "top_ce_buildup": self._take(option_flow.get("ce_oi_buildup_strikes"), 4),
            "top_pe_buildup": self._take(option_flow.get("pe_oi_buildup_strikes"), 4),
            "top_ce_unwinding": self._take(option_flow.get("ce_oi_unwinding_strikes"), 3),
            "top_pe_unwinding": self._take(option_flow.get("pe_oi_unwinding_strikes"), 3),
        }

    def _compact_oi_data(self, data: dict) -> dict:
        snapshot = data.get("snapshot") if isinstance(data, dict) else data
        if not isinstance(snapshot, dict):
            return {"snapshot": snapshot}
        return {
            "symbol": snapshot.get("symbol"),
            "expiry": snapshot.get("expiry"),
            "spot_price": snapshot.get("spot_price"),
            "atm_strike": snapshot.get("atm_strike"),
            "pcr_oi": snapshot.get("pcr_oi"),
            "pcr_volume": snapshot.get("pcr_volume"),
            "chain_bias": snapshot.get("chain_bias"),
            "support_strike": snapshot.get("support_strike"),
            "resistance_strike": snapshot.get("resistance_strike"),
            "snapshot_at": snapshot.get("snapshot_at"),
        }

    def _compact_participant_flow(self, data: dict) -> dict:
        if not isinstance(data, dict):
            return {}
        return {
            "status": data.get("participant_context_status") or data.get("status"),
            "bias": data.get("participant_bias") or data.get("bias"),
            "score": data.get("participant_score") or data.get("score"),
            "warnings": self._take(data.get("warnings"), 4),
            "missing_data": self._take(data.get("missing_data"), 4),
            "reasons": self._take(data.get("reasons"), 4),
        }

    def _take(self, value: Any, limit: int) -> list:
        if not isinstance(value, list):
            return []
        return value[:limit]

    async def generate_post_market_report(self, 
                                          performance_metrics: dict, 
                                          trades: list,
                                          market_context: dict,
                                          provider: str | None = None) -> dict:
        """
        Generates automatic post-market summary reports highlighting trading desk performance.
        """
        prompt = f"""
        You are a tough, analytical Head of Trading. Review today's automated trading performance.
        Return a structured JSON response evaluating the algorithm's decisions.
        
        Data context:
        - Overall Metrics: {json.dumps(performance_metrics)}
        - Trades Taken: {json.dumps(trades)}
        - Overall Market Context: {json.dumps(market_context)}
        
        Required JSON Schema:
        {{
            "performance_rating": "A" | "B" | "C" | "D" | "F",
            "summary": "A markdown-formatted comprehensive review of the day's performance",
            "what_went_right": ["bullet point 1", "bullet point 2"],
            "what_went_wrong": ["bullet point 1", "bullet point 2"],
            "suggestions_for_improvement": ["bullet point 1", "bullet point 2"],
            "market_regime_identified": "Trend Day, Range Bound, High Volatility, etc."
        }}
        """
        return await self._get_json_response(prompt, provider=provider)

    async def synthesize_agent_evolution(
        self,
        analysis_report: dict,
        recommendations: list[dict],
        provider: str | None = None,
    ) -> dict:
        """
        Synthesizes the nightly Agent Evolution rule output into a concise review.
        This intentionally reuses the existing AI analyst provider wiring.
        """
        compact_report = {
            "run_id": analysis_report.get("run_id"),
            "lookback_days": analysis_report.get("lookback_days"),
            "trade_summary": analysis_report.get("trade_summary"),
            "confidence_calibration": analysis_report.get("confidence_calibration"),
            "filter_scorecard": {
                "status": (analysis_report.get("filter_scorecard") or {}).get("status"),
                "harmful_filters": (analysis_report.get("filter_scorecard") or {}).get("harmful_filters", []),
                "helpful_filters": (analysis_report.get("filter_scorecard") or {}).get("helpful_filters", []),
                "filters": self._take((analysis_report.get("filter_scorecard") or {}).get("filters"), 10),
            },
            "failure_patterns": self._take(analysis_report.get("failure_patterns"), 10),
        }
        compact_recommendations = [
            {
                "id": item.get("id"),
                "recommendation_type": item.get("recommendation_type"),
                "affected_module": item.get("affected_module"),
                "issue_detected": item.get("issue_detected"),
                "suggested_change": item.get("suggested_change"),
                "risk_level": item.get("risk_level"),
                "confidence": item.get("confidence"),
            }
            for item in recommendations[:8]
        ]

        prompt = f"""
        You are the nightly synthesis layer for an Indian options trading Agent Evolution Engine.
        The rule engine has already produced analysis and candidate recommendations. Do not invent
        new integrations, do not approve live trading, and do not auto-apply changes.

        Data context:
        - Analysis report: {json.dumps(compact_report, default=str)}
        - Rule recommendations: {json.dumps(compact_recommendations, default=str)}

        Required JSON Schema:
        {{
            "run_quality": "GOOD" | "LIMITED" | "INSUFFICIENT" | "RISKY",
            "executive_summary": "2-4 sentences explaining what the engine learned tonight.",
            "key_mistakes": ["specific mistake or weakness found in evidence"],
            "recommended_human_actions": ["review action before changing config"],
            "do_not_change": ["rules or modules that should remain unchanged for now"],
            "confidence": 1-100,
            "requires_more_data": true | false
        }}
        """
        return await self._get_json_response(prompt, provider=provider)

ai_analyst_service = AiAnalystService()
