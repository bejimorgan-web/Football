from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.storage import authenticate_admin

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthLoginPayload(BaseModel):
    email: str
    password: str
    device_id: str = ""


@router.post("/login")
def auth_login(payload: AuthLoginPayload):
    try:
        session = authenticate_admin(payload.email, payload.password, payload.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {
        "access_token": session.get("api_token", ""),
        "token_type": "bearer",
        "api_token": session.get("api_token", ""),
        "device_id": session.get("device_id", ""),
        "admin": session.get("admin", {}),
    }
