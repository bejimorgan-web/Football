from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_role
from app.mobile_builder import (
    append_worker_build_log,
    cancel_mobile_build,
    claim_next_build_for_worker,
    complete_build_from_worker,
    fail_build_from_worker,
    get_build_download_details,
    get_build_for_worker,
    get_build_status,
    list_build_history,
    queue_mobile_build,
    update_build_from_worker,
)
from app.storage import get_branding_config, get_mobile_runtime_manifest

router = APIRouter()
ADMIN_ACCESS = Depends(require_role("master", "client"))


class WorkerClaimPayload(BaseModel):
    worker_id: str = Field(default="")


class WorkerUpdatePayload(BaseModel):
    progress: int | None = None
    status: str | None = None
    error: str | None = None
    log: str = ""


class WorkerArtifactPayload(BaseModel):
    artifact_name: str = ""
    artifact_path: str = ""
    artifact_storage: str = "local"
    artifact_key: str = ""
    artifact_url: str = ""


def _require_mobile_worker_token(x_mobile_worker_token: str | None = Header(default=None)):
    configured = str(os.environ.get("MOBILE_BUILD_WORKER_TOKEN") or "").strip()
    if not configured:
        raise HTTPException(status_code=401, detail="Mobile build worker token is not configured.")
    presented = str(x_mobile_worker_token or "").strip()
    if not presented or not secrets.compare_digest(presented, configured):
        raise HTTPException(status_code=401, detail="Invalid mobile build worker token.")
    return True


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
def create_mobile_build():
    return {"status": "ok"}


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
        download = get_build_download_details(admin_id, build_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if str(download.get("type") or "") == "redirect":
        return RedirectResponse(str(download.get("download_url") or ""), status_code=307)
    artifact_path = str(download.get("artifact_path") or "")
    return FileResponse(path=artifact_path, filename=str(download.get("artifact_name") or "mobile-build.apk"), media_type="application/vnd.android.package-archive")


@router.get("/build/history")
def mobile_build_history(current_user: dict = Depends(get_current_user)):
    admin_id = str(current_user.get("admin_id") or "").strip()
    items = list_build_history(admin_id)
    latest = items[0] if items else None
    status = get_build_status(admin_id, str(latest.get("build_id") or "")) if latest else None
    return {"items": items, "status": status}


@router.post("/worker/claim")
def mobile_worker_claim(payload: WorkerClaimPayload):
    try:
        worker_id = str(payload.worker_id or "").strip() or "remote-worker"
        job = claim_next_build_for_worker(worker_id)

        if not isinstance(job, dict):
            return {"status": "no_job"}

        return {"status": "ok", "job": job}

    except Exception as exc:
        return {"status": "error", "message": str(exc)}

@router.get("/worker/build/{build_id}")
def mobile_worker_get_build(build_id: str, _: bool = Depends(_require_mobile_worker_token)):
    try:
        return get_build_for_worker(build_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/worker/build/{build_id}/update")
def mobile_worker_update_build(build_id: str, payload: WorkerUpdatePayload, _: bool = Depends(_require_mobile_worker_token)):
    patch = {}
    if payload.progress is not None:
        patch["progress"] = int(payload.progress)
    if payload.status is not None and str(payload.status).strip():
        patch["status"] = str(payload.status).strip()
    if payload.error is not None:
        patch["error"] = str(payload.error)
    try:
        updated = update_build_from_worker(build_id, patch)
        if payload.log:
            updated = append_worker_build_log(build_id, payload.log)
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/worker/build/{build_id}/complete")
def mobile_worker_complete_build(build_id: str, payload: WorkerArtifactPayload, _: bool = Depends(_require_mobile_worker_token)):
    try:
        return complete_build_from_worker(build_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/worker/build/{build_id}/fail")
def mobile_worker_fail_build(build_id: str, payload: WorkerUpdatePayload, _: bool = Depends(_require_mobile_worker_token)):
    try:
        return fail_build_from_worker(
            build_id,
            str(payload.error or "Build failed."),
            cancelled=str(payload.status or "").strip().lower() == "cancelled",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
