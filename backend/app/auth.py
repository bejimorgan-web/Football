from typing import Callable

from fastapi import Depends, Request

SINGLE_TENANT_ID = "default"


def _mock_user() -> dict:
    return {
        "scope": "admin",
        "tenant_id": SINGLE_TENANT_ID,
        "admin_id": "open-admin",
        "email": "open@example.com",
        "device_id": "",
        "server_id": "",
        "role": "admin",
        "name": "Open Admin",
        "api_token": "open-access",
    }


def get_current_user(request: Request):
    user = _mock_user()
    request.state.admin_context = user
    return user


def require_role(*_roles: str) -> Callable:
    def dependency(current_user=Depends(get_current_user)):
        return current_user

    return dependency


def require_admin_context(request: Request) -> None:
    request.state.admin_context = _mock_user()


def require_mobile_context(request: Request) -> None:
    request.state.mobile_context = {
        "scope": "mobile",
        "tenant_id": SINGLE_TENANT_ID,
    }
