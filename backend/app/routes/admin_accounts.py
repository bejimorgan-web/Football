from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.auth import require_role
from app.storage import (
    admin_session_payload,
    authenticate_admin,
    list_admin_summaries,
    register_admin,
    renew_admin_subscription,
    validate_admin_api_token,
)

router = APIRouter()


class AdminRegisterPayload(BaseModel):
    name: str
    email: str
    password: str
    plan_id: str = "trial"
    device_id: str
    payment_provider: Optional[str] = ""
    payment_reference: Optional[str] = ""


class AdminLoginPayload(BaseModel):
    email: str
    password: str
    device_id: str


class AdminRenewPayload(BaseModel):
    api_token: str
    plan_id: str = "1_year"
    payment_provider: Optional[str] = ""
    payment_reference: Optional[str] = ""


@router.post("/register")
def admin_register_account(payload: AdminRegisterPayload):
    try:
        return register_admin(
            name=payload.name,
            email=payload.email,
            password=payload.password,
            plan_id=payload.plan_id,
            device_id=payload.device_id,
            payment_provider=payload.payment_provider or "",
            payment_reference=payload.payment_reference or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login")
def admin_login_account(payload: AdminLoginPayload):
    try:
        return authenticate_admin(payload.email, payload.password, payload.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/validate")
def admin_validate_account(
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


@router.post("/renew")
def admin_renew_account(payload: AdminRenewPayload):
    try:
        return {
            "admin": renew_admin_subscription(
                api_token=payload.api_token,
                plan_id=payload.plan_id,
                payment_provider=payload.payment_provider or "",
                payment_reference=payload.payment_reference or "",
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/list")
def admin_list_accounts(_: dict = Depends(require_role("master"))):
    return {"items": list_admin_summaries()}
