import secrets
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.settings import load_admin_settings_from_env
from app.storage import validate_admin_api_token

security = HTTPBasic(auto_error=False)
SINGLE_TENANT_ID = "default"


def _admin_context_from_token(admin: dict) -> dict:
    return {
        "scope": "admin",
        "tenant_id": SINGLE_TENANT_ID,
        "admin_id": admin.get("admin_id"),
        "email": admin.get("email"),
        "device_id": admin.get("device_id"),
        "server_id": admin.get("server_id"),
        "role": "admin",
    }


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_device_id: Optional[str] = Header(default=None),
    x_server_id: Optional[str] = Header(default=None),
):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Admin token required.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        admin = validate_admin_api_token(
            token,
            device_id=str(x_device_id or "").strip(),
            server_id=str(x_server_id or "").strip(),
            require_server=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    request.state.admin_context = _admin_context_from_token(admin)
    return admin


def require_role(*_roles: str) -> Callable:
    def dependency(current_user=Depends(get_current_user)):
        return current_user

    return dependency


def require_admin_context(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
    authorization: Optional[str] = Header(default=None),
    x_device_id: Optional[str] = Header(default=None),
    x_server_id: Optional[str] = Header(default=None),
) -> None:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            admin = validate_admin_api_token(
                token,
                device_id=str(x_device_id or "").strip(),
                server_id=str(x_server_id or "").strip(),
                require_server=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        request.state.admin_context = _admin_context_from_token(admin)
        return

    admin_settings = load_admin_settings_from_env()
    if not admin_settings.username or not admin_settings.password:
        request.state.admin_context = {
            "scope": "admin",
            "tenant_id": SINGLE_TENANT_ID,
            "username": "open-admin",
            "role": "admin",
        }
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

    request.state.admin_context = {
        "scope": "admin",
        "tenant_id": SINGLE_TENANT_ID,
        "username": credentials.username,
        "role": "admin",
    }


def require_mobile_context(request: Request) -> None:
    request.state.mobile_context = {
        "scope": "mobile",
        "tenant_id": SINGLE_TENANT_ID,
    }
