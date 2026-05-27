from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings, settings


class DhanAuthService:
    """Manages Dhan access-token generation without enabling order placement."""

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.timeout = httpx.Timeout(10.0)

    def status(self) -> dict[str, Any]:
        cached = self.read_cached_token()
        active_token = self.active_access_token()
        auth_status = self.auth_status(cached, active_token)
        return {
            "ok": True,
            "provider": "DHAN",
            "status": auth_status,
            "enabled": self.settings.enable_dhan_api_key_auth,
            "has_client_id": bool(self.settings.dhan_client_id),
            "has_api_key": bool(self.settings.dhan_api_key),
            "has_api_secret": bool(self.settings.dhan_api_secret),
            "has_env_access_token": bool(self.settings.dhan_access_token),
            "has_cached_access_token": bool(cached.get("accessToken")),
            "cached_token_valid": self.cached_token_is_valid(cached),
            "active_token_available": bool(active_token),
            "active_token_source": self.active_token_source(),
            "expiry_time": cached.get("expiryTime"),
            "redirect_url": self.settings.dhan_redirect_url,
            "token_exposed": False,
            "usage": "MARKET_DATA_AUTH_ONLY",
            "order_placement": "DISABLED",
        }

    def auth_status(self, cached: dict[str, Any] | None = None, active_token: str | None = None) -> str:
        cached_payload = cached if cached is not None else self.read_cached_token()
        token = active_token if active_token is not None else self.active_access_token()
        if token:
            return "TOKEN_READY"
        if self.has_api_credentials():
            return "NEEDS_REAUTH"
        if self.settings.dhan_access_token:
            return "MANUAL_TOKEN_CONFIGURED"
        if cached_payload.get("accessToken") and not self.cached_token_is_valid(cached_payload):
            return "NEEDS_REAUTH"
        return "NOT_CONFIGURED"

    def needs_reauth(self) -> bool:
        return self.auth_status() == "NEEDS_REAUTH"

    def has_api_credentials(self) -> bool:
        return bool(
            self.settings.enable_dhan_api_key_auth
            and self.settings.dhan_client_id
            and self.settings.dhan_api_key
            and self.settings.dhan_api_secret
        )

    def active_access_token(self) -> str | None:
        cached = self.read_cached_token()
        if self.cached_token_is_valid(cached):
            token = cached.get("accessToken")
            return str(token) if token else None
        return self.settings.dhan_access_token

    def active_token_source(self) -> str:
        cached = self.read_cached_token()
        if self.cached_token_is_valid(cached) and cached.get("accessToken"):
            return "CACHE"
        if self.settings.dhan_access_token:
            return "ENV"
        return "NONE"

    async def generate_consent(self) -> dict[str, Any]:
        missing = self._missing_api_credentials()
        if missing:
            return {
                "ok": False,
                "status": "CREDENTIALS_MISSING",
                "message": f"Missing Dhan API auth settings: {', '.join(missing)}",
                "token_exposed": False,
            }

        url = (
            f"{self.settings.dhan_auth_base_url.rstrip('/')}/app/generate-consent"
            f"?client_id={quote(self.settings.dhan_client_id or '', safe='')}"
        )
        headers = self._api_auth_headers()
        response = await self._request("POST", url, headers=headers)
        if not response.get("ok"):
            return response

        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        consent_id = data.get("consentAppId")
        if not consent_id:
            return {
                "ok": False,
                "status": "INVALID_RESPONSE",
                "message": "Dhan consent response did not include consentAppId.",
                "token_exposed": False,
                "data": self._redact(data),
            }

        login_url = self.login_url_for_consent(str(consent_id))
        return {
            "ok": True,
            "status": "CONSENT_GENERATED",
            "message": "Open login_url in browser, approve Dhan login, then Dhan will redirect back with tokenId.",
            "consentAppId": consent_id,
            "consentAppStatus": data.get("consentAppStatus"),
            "login_url": login_url,
            "redirect_url": self.settings.dhan_redirect_url,
            "token_exposed": False,
        }

    def login_url_for_consent(self, consent_app_id: str) -> str:
        consent = quote(consent_app_id, safe="")
        return f"{self.settings.dhan_auth_base_url.rstrip('/')}/login/consentApp-login?consentAppId={consent}"

    async def consume_token_id(self, token_id: str) -> dict[str, Any]:
        if not token_id or not token_id.strip():
            return {
                "ok": False,
                "status": "TOKEN_ID_MISSING",
                "message": "Dhan callback did not include tokenId.",
                "token_exposed": False,
            }

        missing = self._missing_api_credentials()
        if missing:
            return {
                "ok": False,
                "status": "CREDENTIALS_MISSING",
                "message": f"Missing Dhan API auth settings: {', '.join(missing)}",
                "token_exposed": False,
            }

        token = quote(token_id.strip(), safe="")
        url = f"{self.settings.dhan_auth_base_url.rstrip('/')}/app/consumeApp-consent?tokenId={token}"
        response = await self._request("GET", url, headers=self._api_auth_headers())
        if not response.get("ok"):
            return response

        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        access_token = data.get("accessToken")
        expiry_time = data.get("expiryTime")
        if not access_token:
            return {
                "ok": False,
                "status": "INVALID_RESPONSE",
                "message": "Dhan consume-consent response did not include accessToken.",
                "token_exposed": False,
                "data": self._redact(data),
            }

        self.write_cached_token(data)
        self.settings.dhan_access_token = str(access_token)
        return {
            "ok": True,
            "status": "TOKEN_READY",
            "message": "Dhan access token cached for read-only market data.",
            "dhanClientId": data.get("dhanClientId"),
            "expiryTime": expiry_time,
            "active_token_source": "CACHE",
            "token_exposed": False,
            "order_placement": "DISABLED",
        }

    async def renew_active_token(self) -> dict[str, Any]:
        token = self.active_access_token()
        if not token or not self.settings.dhan_client_id:
            return {
                "ok": False,
                "status": "CREDENTIALS_MISSING",
                "message": "No active Dhan token/client id available to renew.",
                "token_exposed": False,
            }

        url = f"{self.settings.dhan_base_url.rstrip('/')}/RenewToken"
        headers = {
            "access-token": token,
            "dhanClientId": self.settings.dhan_client_id,
            "Accept": "application/json",
        }
        response = await self._request("GET", url, headers=headers)
        if not response.get("ok"):
            return response

        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        if not data.get("accessToken"):
            return {
                "ok": False,
                "status": "INVALID_RESPONSE",
                "message": "Dhan renew response did not include accessToken.",
                "token_exposed": False,
                "data": self._redact(data),
            }

        self.write_cached_token(data)
        self.settings.dhan_access_token = str(data["accessToken"])
        return {
            "ok": True,
            "status": "TOKEN_RENEWED",
            "message": "Dhan access token renewed and cached.",
            "expiryTime": data.get("expiryTime"),
            "active_token_source": "CACHE",
            "token_exposed": False,
        }

    def read_cached_token(self) -> dict[str, Any]:
        path = self._cache_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_cached_token(self, token_payload: dict[str, Any]) -> None:
        path = self._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dhanClientId": token_payload.get("dhanClientId"),
            "dhanClientName": token_payload.get("dhanClientName"),
            "dhanClientUcc": token_payload.get("dhanClientUcc"),
            "givenPowerOfAttorney": token_payload.get("givenPowerOfAttorney"),
            "accessToken": token_payload.get("accessToken"),
            "expiryTime": token_payload.get("expiryTime"),
            "cachedAt": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def cached_token_is_valid(self, cached: dict[str, Any] | None = None) -> bool:
        payload = cached if cached is not None else self.read_cached_token()
        if not payload or not payload.get("accessToken"):
            return False
        expiry = self._parse_expiry(payload.get("expiryTime"))
        if expiry is None:
            return False
        # Keep a small safety buffer so a nearly expired token is not selected.
        return expiry > datetime.now(timezone.utc) + timedelta(minutes=2)

    async def _request(self, method: str, url: str, headers: dict[str, str]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, url, headers=headers)
        except httpx.TimeoutException:
            return {
                "ok": False,
                "status": "TIMEOUT",
                "message": "Dhan auth request timed out.",
                "token_exposed": False,
            }
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "status": "API_ERROR",
                "message": f"Dhan auth request failed: {type(exc).__name__}.",
                "token_exposed": False,
            }

        data = self._safe_json(response)
        if response.status_code >= 400:
            return {
                "ok": False,
                "status": "API_ERROR",
                "message": f"Dhan auth API returned HTTP {response.status_code}.",
                "http_status": response.status_code,
                "data": self._redact(data),
                "token_exposed": False,
            }
        return {
            "ok": True,
            "status": "CONNECTED",
            "message": "Dhan auth request completed.",
            "data": data,
            "token_exposed": False,
        }

    def _api_auth_headers(self) -> dict[str, str]:
        return {
            "app_id": self.settings.dhan_api_key or "",
            "app_secret": self.settings.dhan_api_secret or "",
            "Accept": "application/json",
        }

    def _missing_api_credentials(self) -> list[str]:
        missing: list[str] = []
        if not self.settings.enable_dhan_api_key_auth:
            missing.append("ENABLE_DHAN_API_KEY_AUTH=true")
        if not self.settings.dhan_client_id:
            missing.append("DHAN_CLIENT_ID")
        if not self.settings.dhan_api_key:
            missing.append("DHAN_API_KEY")
        if not self.settings.dhan_api_secret:
            missing.append("DHAN_API_SECRET")
        return missing

    def _cache_path(self) -> Path:
        return Path(self.settings.dhan_token_cache_path)

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if "token" in lowered or "secret" in lowered or "access" in lowered:
                    redacted[key] = "[REDACTED]"
                else:
                    redacted[key] = cls._redact(item)
            return redacted
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        return value

    @staticmethod
    def _parse_expiry(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            raw = str(value).strip().replace("Z", "+00:00")
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            # Dhan docs define expiryTime as IST for API-key flow.
            parsed = parsed.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        return parsed.astimezone(timezone.utc)


def get_dhan_auth_service() -> DhanAuthService:
    return DhanAuthService(settings)


def get_active_dhan_access_token(app_settings: Settings = settings) -> str | None:
    return DhanAuthService(app_settings).active_access_token()


def has_active_dhan_credentials(app_settings: Settings = settings) -> bool:
    return bool(app_settings.dhan_client_id and get_active_dhan_access_token(app_settings))


def dhan_auth_needs_reauth(app_settings: Settings = settings) -> bool:
    return DhanAuthService(app_settings).needs_reauth()
