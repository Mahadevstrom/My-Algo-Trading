from fastapi import HTTPException, status

from app.config import settings


def ensure_live_orders_disabled() -> None:
    if not settings.allow_live_orders or not settings.enable_dhan_order_placement:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Live orders are disabled. Paper trading only.",
        )

