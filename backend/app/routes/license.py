from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import get_current_user, require_role
from app.settings import is_development_mode
from app.storage import (
    activate_license_key,
    generate_license_for_admin,
    get_admin_license,
    reassign_license,
    revoke_license,
    validate_license_token_payload,
)

router = APIRouter()


class LicenseGeneratePayload(BaseModel):
    admin_id: Optional[str] = None
    activation_limit: int = 1


class LicenseActivatePayload(BaseModel):
    license_key: str
    device_id: str
    app_version: str = ""


class LicenseValidatePayload(BaseModel):
    license_token: str
    device_id: str


class LicenseActionPayload(BaseModel):
    license_key: str


def _enforce_https(request: Request) -> None:
    if request.url.scheme != "https" and not is_development_mode():
        raise HTTPException(status_code=400, detail="License endpoints require HTTPS outside local development.")


@router.post("/generate")
def license_generate(payload: LicenseGeneratePayload, request: Request, current_user: dict = Depends(require_role("master", "client"))):
    _enforce_https(request)
    target_admin_id = str(payload.admin_id or current_user.get("admin_id") or "")
    if str(current_user.get("role") or "") != "master" and target_admin_id != str(current_user.get("admin_id") or ""):
        raise HTTPException(status_code=403, detail="You can only generate licenses for your own admin account.")
    try:
        item = get_admin_license(target_admin_id) or generate_license_for_admin(admin_id=target_admin_id, activation_limit=payload.activation_limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"license": item}


@router.post("/activate")
def license_activate(payload: LicenseActivatePayload, request: Request):
    _enforce_https(request)
    try:
        return activate_license_key(
            license_key=payload.license_key,
            device_id=payload.device_id,
            app_version=payload.app_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/validate")
def license_validate(payload: LicenseValidatePayload, request: Request):
    _enforce_https(request)
    try:
        return validate_license_token_payload(
            license_token=payload.license_token,
            device_id=payload.device_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/revoke")
def license_revoke(payload: LicenseActionPayload, request: Request, current_user: dict = Depends(require_role("master", "client"))):
    _enforce_https(request)
    try:
        return {"license": revoke_license(admin_id=str(current_user.get("admin_id") or ""), license_key=payload.license_key)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reassign")
def license_reassign(payload: LicenseActionPayload, request: Request, current_user: dict = Depends(require_role("master", "client"))):
    _enforce_https(request)
    try:
        return {"license": reassign_license(admin_id=str(current_user.get("admin_id") or ""), license_key=payload.license_key)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
