from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.auth import get_current_user, require_admin_context, require_role
from app.storage import (
    get_install_stats,
    get_country_viewers,
    get_daily_viewers,
    get_live_analytics,
    get_stream_live_analytics,
    get_top_competitions,
    get_top_matches,
    register_install_event,
    register_subscription_event,
)

router = APIRouter()
router.dependencies.append(Depends(require_admin_context))


class InstallPayload(BaseModel):
    admin_id: str
    device_id: str
    app_version: str
    timestamp: str = ""


class SubscriptionPayload(BaseModel):
    admin_id: str
    subscription_plan: str
    start_date: str
    end_date: str


def _scoped_tenant_id(request: Request, tenant_id: str) -> str:
    context = getattr(request.state, "admin_context", {"scope": "platform", "tenant_id": None})
    if context.get("scope") in {"tenant", "admin"}:
        if str(context.get("role") or "").strip().lower() == "master":
            return str(tenant_id or context.get("tenant_id") or "default")
        return str(context.get("tenant_id") or "default")
    return tenant_id


def _assert_admin_scope(request: Request, admin_id: str) -> None:
    context = getattr(request.state, "admin_context", {"scope": "platform", "admin_id": None})
    if context.get("scope") == "platform":
        return
    if str(context.get("admin_id") or "") != str(admin_id or ""):
        raise HTTPException(status_code=403, detail="Tracking payload does not match the authenticated admin.")


ANALYTICS_ACCESS = Depends(require_role("master", "client"))


@router.get("/live")
def analytics_live(request: Request, tenant_id: str = Query("default"), _: dict = ANALYTICS_ACCESS):
    return get_live_analytics(tenant_id=_scoped_tenant_id(request, tenant_id))


@router.get("/streams")
def analytics_streams(request: Request, tenant_id: str = Query("default"), _: dict = ANALYTICS_ACCESS):
    return {"items": get_stream_live_analytics(tenant_id=_scoped_tenant_id(request, tenant_id))}


@router.get("/top-matches")
def analytics_top_matches(request: Request, limit: int = Query(10, ge=1, le=100), today_only: bool = True, tenant_id: str = Query("default"), _: dict = ANALYTICS_ACCESS):
    return {"items": get_top_matches(limit=limit, today_only=today_only, tenant_id=_scoped_tenant_id(request, tenant_id))}


@router.get("/top-competitions")
def analytics_top_competitions(request: Request, limit: int = Query(10, ge=1, le=100), today_only: bool = True, tenant_id: str = Query("default"), _: dict = ANALYTICS_ACCESS):
    return {"items": get_top_competitions(limit=limit, today_only=today_only, tenant_id=_scoped_tenant_id(request, tenant_id))}


@router.get("/daily-viewers")
def analytics_daily_viewers(request: Request, days: int = Query(14, ge=1, le=365), tenant_id: str = Query("default"), _: dict = ANALYTICS_ACCESS):
    return {"items": get_daily_viewers(days=days, tenant_id=_scoped_tenant_id(request, tenant_id))}


@router.get("/countries")
def analytics_countries(request: Request, limit: int = Query(20, ge=1, le=100), tenant_id: str = Query("default"), _: dict = ANALYTICS_ACCESS):
    return {"items": get_country_viewers(limit=limit, tenant_id=_scoped_tenant_id(request, tenant_id))}


@router.post("/register-install")
def analytics_register_install(request: Request, payload: InstallPayload, current_user: dict = Depends(get_current_user)):
    del current_user
    _assert_admin_scope(request, payload.admin_id)
    try:
        return {"item": register_install_event(**payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/register-subscription")
def analytics_register_subscription(request: Request, payload: SubscriptionPayload, current_user: dict = Depends(get_current_user)):
    del current_user
    _assert_admin_scope(request, payload.admin_id)
    try:
        return {"item": register_subscription_event(**payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/install-stats")
def analytics_install_stats(request: Request, _: dict = Depends(require_role("master"))):
    del request
    return get_install_stats()
