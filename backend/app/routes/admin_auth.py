from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.storage import (
    admin_session_payload,
    authenticate_admin,
    register_admin,
    register_admin_server,
    reset_admin_server,
    transfer_admin_device,
    validate_admin_api_token,
)

router = APIRouter()


class AdminRegisterPayload(BaseModel):
    name: str
    email: str
    password: str
    plan_id: str = "trial"
    device_id: str


class AdminLoginPayload(BaseModel):
    email: str
    password: str
    device_id: str


class ServerRegisterPayload(BaseModel):
    api_token: str
    server_domain: Optional[str] = ""
    server_ip: Optional[str] = ""
    hardware_hash: Optional[str] = ""
    device_id: Optional[str] = ""


class ServerResetPayload(BaseModel):
    api_token: str
    device_id: Optional[str] = ""


class DeviceTransferPayload(BaseModel):
    api_token: str
    device_id: str


@router.post("/register")
def admin_register(payload: AdminRegisterPayload):
    try:
        return register_admin(
            name=payload.name,
            email=payload.email,
            password=payload.password,
            plan_id=payload.plan_id,
            device_id=payload.device_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login")
def admin_login(payload: AdminLoginPayload):
    try:
        return authenticate_admin(payload.email, payload.password, payload.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/validate")
def admin_validate(
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
    return {"admin": admin_session_payload(admin)}


@router.post("/register-server")
def admin_register_server(payload: ServerRegisterPayload):
    try:
        return {"admin": register_admin_server(**payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset-server")
def admin_reset_server(payload: ServerResetPayload):
    try:
        return {"admin": reset_admin_server(**payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transfer-device")
def admin_transfer_device(payload: DeviceTransferPayload):
    try:
        return transfer_admin_device(api_token=payload.api_token, next_device_id=payload.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
