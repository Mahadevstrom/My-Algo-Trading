from pydantic import BaseModel
from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from app.services.dhan_auth_service import get_dhan_auth_service


router = APIRouter(prefix="/api/dhan-auth", tags=["dhan-auth"])


class DhanConsumeTokenRequest(BaseModel):
    tokenId: str


@router.get("/status")
def dhan_auth_status() -> dict:
    return get_dhan_auth_service().status()


@router.post("/generate-consent")
async def dhan_generate_consent() -> dict:
    return await get_dhan_auth_service().generate_consent()


@router.get("/login-url")
async def dhan_login_url() -> dict:
    return await get_dhan_auth_service().generate_consent()


@router.get("/login")
async def dhan_login_redirect():
    result = await get_dhan_auth_service().generate_consent()
    if result.get("ok") and result.get("login_url"):
        return RedirectResponse(str(result["login_url"]))
    return result


@router.get("/callback")
async def dhan_auth_callback(tokenId: str | None = Query(default=None)) -> dict:
    return await get_dhan_auth_service().consume_token_id(tokenId or "")


@router.post("/consume")
async def dhan_consume_token(payload: DhanConsumeTokenRequest) -> dict:
    return await get_dhan_auth_service().consume_token_id(payload.tokenId)


@router.post("/renew")
async def dhan_renew_token() -> dict:
    return await get_dhan_auth_service().renew_active_token()
