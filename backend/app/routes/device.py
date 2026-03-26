from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.auth import require_mobile_context
from app.storage import get_device_status, register_device

router = APIRouter()


class DeviceRegisterPayload(BaseModel):
    tenant_id: Optional[str] = "default"
    device_id: str
    device_name: str
    platform: str
    app_version: str
    device_fingerprint: Optional[str] = None
    country: Optional[str] = None
    vpn_active: Optional[bool] = False
    secure_device: Optional[bool] = True
    app_signature_valid: Optional[bool] = True


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else ""


@router.post("/register")
def device_register(payload: DeviceRegisterPayload, request: Request, _: None = Depends(require_mobile_context)):
    try:
        context = getattr(request.state, "mobile_context", {})
        item = register_device(
            device_id=payload.device_id,
            device_name=payload.device_name,
            platform=payload.platform,
            app_version=payload.app_version,
            tenant_id=context.get("tenant_id") or payload.tenant_id or "default",
            device_fingerprint=payload.device_fingerprint or "",
            ip_address=_client_ip(request),
            country=payload.country or "",
            vpn_active=bool(payload.vpn_active),
            secure_device=bool(payload.secure_device),
            app_signature_valid=bool(payload.app_signature_valid),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.get("/status")
def device_status(
    request: Request,
    tenant_id: str = Query("default"),
    device_id: str = Query(...),
    touch: Optional[bool] = True,
    country: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    vpn_active: Optional[bool] = False,
    secure_device: Optional[bool] = True,
    app_signature_valid: Optional[bool] = True,
    _: None = Depends(require_mobile_context),
):
    try:
        context = getattr(request.state, "mobile_context", {})
        return {
            "item": get_device_status(
                device_id=device_id,
                touch=bool(touch),
                tenant_id=context.get("tenant_id") or tenant_id,
                ip_address=_client_ip(request),
                country=country or "",
                device_fingerprint=device_fingerprint or "",
                vpn_active=bool(vpn_active),
                secure_device=bool(secure_device),
                app_signature_valid=bool(app_signature_valid),
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
