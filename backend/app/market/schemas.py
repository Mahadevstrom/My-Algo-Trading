from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MarketInstrumentsRequest(BaseModel):
    instruments: dict[str, list[int | str]] = Field(..., min_length=1)

    @field_validator("instruments")
    @classmethod
    def validate_instruments(cls, value: dict[str, list[int | str]]) -> dict[str, list[int | str]]:
        cleaned: dict[str, list[int | str]] = {}
        for segment, security_ids in value.items():
            clean_segment = segment.strip().upper()
            if not clean_segment:
                raise ValueError("exchange segment cannot be blank.")
            if not security_ids:
                raise ValueError(f"{clean_segment} must include at least one security id.")
            cleaned[clean_segment] = security_ids
        return cleaned


class HistoricalDailyRequest(BaseModel):
    security_id: str
    exchange_segment: str
    instrument: str
    from_date: date
    to_date: date

    @field_validator("security_id", "exchange_segment", "instrument", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return str(value).strip()


class IntradayRequest(HistoricalDailyRequest):
    interval: str

    @field_validator("interval", mode="before")
    @classmethod
    def strip_interval(cls, value: str) -> str:
        return str(value).strip()


class OptionExpiryRequest(BaseModel):
    under_security_id: str
    under_exchange_segment: str

    @field_validator("under_security_id", "under_exchange_segment", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return str(value).strip()


class OptionChainRequest(OptionExpiryRequest):
    expiry: date | None = None

    @field_validator("expiry", mode="before")
    @classmethod
    def empty_expiry_to_none(cls, value: object) -> object:
        if value is None or str(value).strip() == "":
            return None
        return value

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "under_security_id": "13",
                    "under_exchange_segment": "IDX_I",
                    "expiry": "2026-05-12",
                }
            ]
        }
    }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_response(
    ok: bool,
    connected: bool,
    status: str,
    message: str,
    data: Any = None,
    source: str = "DHAN",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "connected": connected,
        "status": status,
        "message": message,
        "source": source,
        "timestamp": utc_timestamp(),
        "data": data,
        **extra,
    }
