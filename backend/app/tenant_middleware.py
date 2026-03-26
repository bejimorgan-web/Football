from __future__ import annotations

from typing import Optional

from fastapi import Request

from app.storage import _normalize_tenant_id, validate_admin_api_token, validate_tenant_access_token


def _header_tenant_id(request: Request) -> str:
    return str(
        request.headers.get("x-tenant-id")
        or request.query_params.get("tenant_id")
        or ""
    ).strip()


def _resolve_bearer_tenant(request: Request, authorization: Optional[str]) -> Optional[dict]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = validate_tenant_access_token(token)
        return {
            "tenant_id": _normalize_tenant_id(payload.get("tenant_id")),
            "source": "tenant_token",
            "scope": "tenant",
        }
    except ValueError:
        try:
            admin = validate_admin_api_token(
                token,
                device_id=str(request.headers.get("x-device-id") or "").strip(),
                server_id=str(request.headers.get("x-server-id") or "").strip(),
                require_server=False,
            )
            return {
                "tenant_id": _normalize_tenant_id(admin.get("tenant_id")),
                "source": "admin_token",
                "scope": "admin",
                "admin_id": str(admin.get("admin_id") or ""),
                "role": str(admin.get("role") or ""),
            }
        except ValueError:
            return None


async def tenant_resolver(request: Request, call_next):
    tenant_context = {
        "tenant_id": _normalize_tenant_id(_header_tenant_id(request) or "default"),
        "source": "header",
        "scope": "request",
    }
    resolved = _resolve_bearer_tenant(request, request.headers.get("authorization"))
    if resolved is not None:
        tenant_context = resolved
    request.state.tenant_context = tenant_context
    response = await call_next(request)
    return response
