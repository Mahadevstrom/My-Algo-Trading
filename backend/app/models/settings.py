from typing import Any

from pydantic import BaseModel


class SettingsResponse(BaseModel):
    settings: dict[str, Any]
    safety_status: dict[str, Any]

