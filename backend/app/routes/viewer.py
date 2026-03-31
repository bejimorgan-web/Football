from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import SINGLE_TENANT_ID, require_mobile_context
from app.storage import get_device_status, start_viewer_session, stop_viewer_session

router = APIRouter()


class ViewerStartPayload(BaseModel):
    tenant_id: Optional[str] = SINGLE_TENANT_ID
    device_id: str
    stream_id: str
    competition: str
    home_club: str
    away_club: str
    timestamp: Optional[str] = None
    country: Optional[str] = None


class ViewerStopPayload(BaseModel):
    tenant_id: Optional[str] = SINGLE_TENANT_ID
    device_id: str
    stream_id: str
    timestamp: Optional[str] = None


@router.post("/start")
def viewer_start(payload: ViewerStartPayload, request: Request, _: None = Depends(require_mobile_context)):
    try:
        context = getattr(request.state, "mobile_context", {})
        tenant_id = context.get("tenant_id") or SINGLE_TENANT_ID
        status = get_device_status(device_id=payload.device_id, touch=True, tenant_id=tenant_id)
        if not status.get("is_allowed"):
            raise ValueError(str(status.get("message") or "Access denied."))
        item = start_viewer_session(
            tenant_id=tenant_id,
            device_id=payload.device_id,
            stream_id=payload.stream_id,
            competition=payload.competition,
            home_club=payload.home_club,
            away_club=payload.away_club,
            timestamp=payload.timestamp,
            country=payload.country,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.post("/stop")
def viewer_stop(payload: ViewerStopPayload, request: Request, _: None = Depends(require_mobile_context)):
    try:
        context = getattr(request.state, "mobile_context", {})
        item = stop_viewer_session(
            tenant_id=context.get("tenant_id") or SINGLE_TENANT_ID,
            device_id=payload.device_id,
            stream_id=payload.stream_id,
            timestamp=payload.timestamp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}
