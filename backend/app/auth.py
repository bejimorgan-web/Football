import logging
import secrets
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.settings import load_admin_settings_from_env
from app.storage import _normalize_admin_role, _normalize_tenant_id, validate_admin_api_token, validate_mobile_tenant_access, validate_tenant_access_token

security = HTTPBasic(auto_error=False)
logger = logging.getLogger("football_iptv.auth")


def _requested_tenant_id(request: Request) -> str:
    return str(
        request.headers.get("x-tenant-id")
        or request.query_params.get("tenant_id")
        or ""
    ).strip()


def _enforce_token_tenant_match(request: Request, token_tenant_id: object) -> None:
    requested_tenant = _requested_tenant_id(request)
    if not requested_tenant:
        return
    normalized_token_tenant = _normalize_tenant_id(token_tenant_id)
    normalized_requested_tenant = _normalize_tenant_id(requested_tenant)
    if normalized_token_tenant != normalized_requested_tenant:
        logger.warning(
            "Token tenant %s does not match request tenant %s for %s",
            normalized_token_tenant,
            normalized_requested_tenant,
            request.url.path,
        )
        raise HTTPException(status_code=401, detail="Token tenant does not match requested tenant.")


def _set_admin_context(request: Request, admin: dict) -> dict:
    context = {
        "scope": "admin",
        "tenant_id": admin.get("tenant_id"),
        "admin_id": admin.get("admin_id"),
        "email": admin.get("email"),
        "device_id": admin.get("device_id"),
        "server_id": admin.get("server_id"),
        "role": _normalize_admin_role(admin.get("role"), default="client"),
    }
    request.state.admin_context = context
    return admin


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_device_id: Optional[str] = Header(default=None),
    x_server_id: Optional[str] = Header(default=None),
):
    if not authorization or not authorization.lower().startswith("bearer "):
        logger.warning(
            "Admin auth rejected for %s: missing bearer token device_id_present=%s server_id_present=%s",
            request.url.path,
            bool(str(x_device_id or "").strip()),
            bool(str(x_server_id or "").strip()),
        )
        raise HTTPException(status_code=401, detail="Admin token required.")
    require_server = not request.url.path.endswith(("/register-server", "/reset-server", "/transfer-device"))
    token = authorization.split(" ", 1)[1].strip()
    try:
        admin = validate_admin_api_token(
            token,
            device_id=str(x_device_id or "").strip(),
            server_id=str(x_server_id or "").strip(),
            require_server=require_server,
        )
    except ValueError as exc:
        logger.warning(
            "Admin auth rejected for %s: %s device_id=%s server_id=%s require_server=%s",
            request.url.path,
            str(exc),
            str(x_device_id or "").strip(),
            str(x_server_id or "").strip(),
            require_server,
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _enforce_token_tenant_match(request, admin.get("tenant_id"))
    return _set_admin_context(request, admin)


def require_role(*roles: str) -> Callable:
    normalized_roles = {_normalize_admin_role(role, default=str(role or "").strip().lower()) for role in roles if str(role or "").strip()}

    def dependency(current_user=Depends(get_current_user)):
        role = _normalize_admin_role(current_user.get("role"), default=str(current_user.get("role") or "").strip().lower())
        if normalized_roles and role not in normalized_roles:
            raise HTTPException(status_code=403, detail="Forbidden: insufficient role.")
        return current_user

    return dependency


def require_admin_context(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
    x_device_id: Optional[str] = Header(default=None),
    x_server_id: Optional[str] = Header(default=None),
) -> None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        require_server = not request.url.path.endswith(("/register-server", "/reset-server", "/transfer-device"))
        try:
            admin = validate_admin_api_token(
                token,
                device_id=str(x_device_id or "").strip(),
                server_id=str(x_server_id or "").strip(),
                require_server=require_server,
            )
            _enforce_token_tenant_match(request, admin.get("tenant_id"))
            _set_admin_context(request, admin)
            return
        except ValueError as admin_exc:
            try:
                payload = validate_tenant_access_token(token)
            except ValueError as exc:
                logger.warning(
                    "Admin context auth rejected for %s: admin_error=%s tenant_error=%s device_id=%s server_id=%s require_server=%s",
                    request.url.path,
                    str(admin_exc),
                    str(exc),
                    str(x_device_id or "").strip(),
                    str(x_server_id or "").strip(),
                    require_server,
                )
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            _enforce_token_tenant_match(request, payload.get("tenant_id"))
            request.state.admin_context = {
                "scope": "tenant",
                "tenant_id": payload.get("tenant_id"),
                "username": payload.get("username"),
                "role": "client",
            }
            return

    admin_settings = load_admin_settings_from_env()
    if not admin_settings.username or not admin_settings.password:
        request.state.admin_context = {"scope": "platform", "tenant_id": None, "username": "open-admin", "role": "master"}
        return

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Admin credentials required.",
            headers={"WWW-Authenticate": "Basic"},
        )

    username_ok = secrets.compare_digest(credentials.username, admin_settings.username)
    password_ok = secrets.compare_digest(credentials.password, admin_settings.password)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid admin credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    request.state.admin_context = {"scope": "platform", "tenant_id": None, "username": credentials.username, "role": "master"}


def require_mobile_context(
    request: Request,
    x_api_token: Optional[str] = Header(default=None),
    x_tenant_id: Optional[str] = Header(default=None),
    x_device_id: Optional[str] = Header(default=None),
    x_server_id: Optional[str] = Header(default=None),
) -> None:
    token = str(x_api_token or "").strip()
    tenant_id = str(x_tenant_id or request.query_params.get("tenant_id") or "").strip()
    device_id = str(x_device_id or request.query_params.get("device_id") or "").strip()
    server_id = str(x_server_id or request.query_params.get("server_id") or "").strip()
    if not token or not tenant_id or not device_id or not server_id:
        raise HTTPException(status_code=403, detail="Tenant-scoped mobile credentials are required.")
    try:
        context = validate_mobile_tenant_access(
            api_token=token,
            tenant_id=tenant_id,
            device_id=device_id,
            server_id=server_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    request.state.mobile_context = context
