from fastapi import APIRouter
from pydantic import BaseModel

from app.auth import SINGLE_TENANT_ID

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthLoginPayload(BaseModel):
    email: str
    password: str
    device_id: str = ""


@router.post("/login")
def auth_login(payload: AuthLoginPayload):
    session = {
        "api_token": "open-access",
        "device_id": payload.device_id,
        "admin": {
            "admin_id": "open-admin",
            "name": "Open Admin",
            "email": payload.email.strip() or "open@example.com",
            "role": "admin",
            "tenant_id": SINGLE_TENANT_ID,
        },
    }
    return {
        "access_token": session.get("api_token", ""),
        "token_type": "bearer",
        "api_token": session.get("api_token", ""),
        "device_id": session.get("device_id", ""),
        "admin": session.get("admin", {}),
    }
