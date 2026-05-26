from fastapi import APIRouter

from app.config import settings
from app.models.settings import SettingsResponse


router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    return SettingsResponse(
        settings=settings.public_dict(),
        safety_status=settings.safety_status,
    )

