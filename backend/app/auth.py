import secrets
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.settings import is_development_mode, load_admin_settings_from_env
from app.storage import _normalize_admin_role, validate_admin_api_token, validate_mobile_tenant_access, validate_tenant_access_token

security = HTTPBasic(auto_error=False)


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
        raise HTTPException(status_code=401, detail=str(exc)) from exc
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
            _set_admin_context(request, admin)
            return
        except ValueError:
            try:
                payload = validate_tenant_access_token(token)
            except ValueError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
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
    if is_development_mode():
        request.state.mobile_context = {
            "scope": "mobile-dev",
            "tenant_id": tenant_id or "master",
            "device_id": device_id or "dev-device",
            "server_id": server_id or "dev-server",
            "api_token": token,
            "mode": "development",
        }
        return
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
