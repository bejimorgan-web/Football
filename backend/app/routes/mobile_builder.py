from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth import get_current_user, require_role
from app.mobile_builder import cancel_mobile_build, get_build_download_path, get_build_status, list_build_history, queue_mobile_build
from app.storage import get_branding_config, get_mobile_runtime_manifest

router = APIRouter()
ADMIN_ACCESS = Depends(require_role("master", "client"))


def _queue_build_for_current_user(current_user: dict):
    admin_id = str(current_user.get("admin_id") or "").strip()
    if not admin_id:
        raise HTTPException(status_code=403, detail="Admin identity required.")
    try:
        job = queue_mobile_build(admin_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job


@router.post("/build")
def create_mobile_build(current_user: dict = ADMIN_ACCESS):
    return _queue_build_for_current_user(current_user)


@router.post("/generate")
def generate_mobile_build(current_user: dict = ADMIN_ACCESS):
    return _queue_build_for_current_user(current_user)


@router.post("/generate-app")
def generate_mobile_app(current_user: dict = ADMIN_ACCESS):
    return _queue_build_for_current_user(current_user)


@router.get("/build/status/{build_id}")
def mobile_build_status(build_id: str, current_user: dict = Depends(get_current_user)):
    admin_id = str(current_user.get("admin_id") or "").strip()
    try:
        return get_build_status(admin_id, build_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/build/cancel/{build_id}")
def mobile_cancel_build(build_id: str, current_user: dict = Depends(get_current_user)):
    admin_id = str(current_user.get("admin_id") or "").strip()
    try:
        return cancel_mobile_build(admin_id, build_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/download/{build_id}")
def mobile_download_build(build_id: str, current_user: dict = Depends(get_current_user)):
    admin_id = str(current_user.get("admin_id") or "").strip()
    try:
        artifact_path = get_build_download_path(admin_id, build_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path=artifact_path, filename=artifact_path.name, media_type="application/vnd.android.package-archive")


@router.get("/build/history")
def mobile_build_history(current_user: dict = Depends(get_current_user)):
    admin_id = str(current_user.get("admin_id") or "").strip()
    items = list_build_history(admin_id)
    latest = items[0] if items else None
    status = get_build_status(admin_id, str(latest.get("build_id") or "")) if latest else None
    return {"items": items, "status": status}


@router.get("/config/{tenant_id}")
def mobile_runtime_config(tenant_id: str):
    tenant = get_branding_config(tenant_id)
    branding = tenant.get("branding") if isinstance(tenant.get("branding"), dict) else {}
    return {
        "tenant_id": tenant.get("tenant_id"),
        "app_name": str(branding.get("app_name") or tenant.get("name") or ""),
        "logo_url": str(branding.get("logo_url") or branding.get("logo_file") or ""),
        "theme_color": str(branding.get("primary_color") or ""),
        "api_url": str(tenant.get("backend_url") or branding.get("server_url") or branding.get("api_base_url") or ""),
        "server_url": str(tenant.get("backend_url") or branding.get("server_url") or branding.get("api_base_url") or ""),
        "server_url_source": str(tenant.get("backend_url_source") or "configured"),
        "server_url_notice": str(tenant.get("backend_url_notice") or ""),
        "streams_endpoint": f"/streams/catalog?tenant_id={tenant.get('tenant_id')}",
        "splash_screen": str(branding.get("splash_screen") or ""),
        "language": tenant.get("language") or {},
        "feature_flags": tenant.get("feature_flags") or {},
        "update_manifest": get_mobile_runtime_manifest(tenant_id),
    }
