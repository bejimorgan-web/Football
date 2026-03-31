import logging
import os
from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api_config import (
    build_public_api_config,
    ensure_api_config_storage,
    get_runtime_backend_api_url,
    get_runtime_public_api_url,
    save_api_config,
)
from app.auth import SINGLE_TENANT_ID, require_admin_context
from app.backup import ensure_backup_storage, start_backup_scheduler, stop_backup_scheduler
from app.branding_engine import BRANDING_CDN_ROOT, BRANDING_STORAGE_ROOT, ensure_branding_storage
from app.logo_utils import STATIC_ROOT, ensure_static_logo_storage
from app.notifications import start_notification_scheduler, stop_notification_scheduler
from app.env_loader import load_backend_env
from app.routes.admin import router as admin_router
from app.routes.auth_login import router as auth_login_router
from app.routes.config import router as config_router
from app.routes.device import router as device_router
from app.routes.playback import router as playback_router
from app.routes.streams import router as streams_router
from app.routes.version import router as version_router
from app.routes.viewer import router as viewer_router
from app.settings import is_development_mode, load_backup_settings_from_env, load_email_settings_from_env, load_settings_from_env, validate_settings
from app.storage import ASSETS_DIR, ensure_storage_files, flush_audit_logs, load_config, log_audit_event, save_config
from app.tenant_middleware import tenant_resolver
from app.update_service import ensure_update_storage

load_backend_env()

logger = logging.getLogger("football_iptv.api")
AUDIT_EXCLUDED_PREFIXES = (
    "/analytics/",
    "/admin/security",
)

def _cors_allowed_origins() -> list[str]:
    return ["*"]


app = FastAPI(title="Football IPTV API")
DOWNLOADS_DIR = Path(__file__).resolve().parent / "downloads"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
ensure_storage_files()
ensure_backup_storage()
ensure_update_storage()
ensure_branding_storage()
ensure_api_config_storage()
ensure_static_logo_storage()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_origin_regex=None,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Api-Token", "X-Tenant-Id", "X-Device-Id", "X-Server-Id"],
    expose_headers=["Content-Type"],
    max_age=86400,
)
app.middleware("http")(tenant_resolver)


def _should_audit_request(request: Request) -> bool:
    if request.method.upper() != "GET":
        return True
    path = request.url.path
    return not any(path.startswith(prefix) for prefix in AUDIT_EXCLUDED_PREFIXES)

app.include_router(streams_router, prefix="/streams", tags=["streams"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(config_router, prefix="/config", tags=["config"])
app.include_router(auth_login_router)
app.include_router(device_router, prefix="/device", tags=["device"])
app.include_router(viewer_router, prefix="/viewer", tags=["viewer"])
app.include_router(playback_router, tags=["playback"])
app.include_router(version_router, tags=["version"])
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
app.mount("/downloads", StaticFiles(directory=DOWNLOADS_DIR), name="downloads")
app.mount("/branding", StaticFiles(directory=BRANDING_STORAGE_ROOT), name="branding")
app.mount("/cdn/branding", StaticFiles(directory=BRANDING_CDN_ROOT), name="branding-cdn")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server error for %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error."},
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = int((perf_counter() - started) * 1000)
        logger.exception(
            "Request failed method=%s path=%s duration_ms=%s",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise
    duration_ms = int((perf_counter() - started) * 1000)
    logger.info(
        "Request completed method=%s path=%s status=%s duration_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.middleware("http")
async def audit_request(request: Request, call_next):
    started = perf_counter()
    response = await call_next(request)
    if not _should_audit_request(request):
        return response
    duration_ms = int((perf_counter() - started) * 1000)
    admin_context = getattr(request.state, "admin_context", None) or {}
    mobile_context = getattr(request.state, "mobile_context", None) or {}
    tenant_context = getattr(request.state, "tenant_context", None) or {}
    scope = str(admin_context.get("scope") or ("mobile" if mobile_context else "anonymous"))
    log_audit_event(
        path=request.url.path,
        method=request.method,
        status_code=response.status_code,
        admin_id=str(admin_context.get("admin_id") or mobile_context.get("admin_id") or ""),
        tenant_id=str(admin_context.get("tenant_id") or mobile_context.get("tenant_id") or tenant_context.get("tenant_id") or ""),
        device_id=str(admin_context.get("device_id") or mobile_context.get("device_id") or request.headers.get("x-device-id") or ""),
        server_id=str(admin_context.get("server_id") or mobile_context.get("server_id") or request.headers.get("x-server-id") or ""),
        scope=scope,
        duration_ms=duration_ms,
    )
    return response


@app.on_event("startup")
def load_env_config() -> None:
    settings = load_settings_from_env()
    backup_settings = load_backup_settings_from_env()
    email_settings = load_email_settings_from_env()
    ok, _ = validate_settings(settings)
    if ok:
        save_config(settings)
    else:
        stored = load_config()
        if stored is not None:
            stored_ok, _ = validate_settings(stored)
            if not stored_ok:
                stored = None

    start_backup_scheduler(backup_settings)
    start_notification_scheduler(email_settings)


@app.on_event("shutdown")
def shutdown_background_services() -> None:
    stop_backup_scheduler()
    stop_notification_scheduler()
    flush_audit_logs(force=True)


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "running"}


class ApiEndpointPayload(BaseModel):
    url: str = ""
    api_token: str = ""
    connected: bool = False


class PublicApiConfigPayload(BaseModel):
    apiBaseUrl: str = ""
    backendApi: ApiEndpointPayload | None = None
    publicApi: ApiEndpointPayload | None = None


@app.get("/api/config")
def api_config(request: Request):
    payload = build_public_api_config()
    backend_api = payload.get("backend_api") if isinstance(payload.get("backend_api"), dict) else {}
    public_api = payload.get("public_api") if isinstance(payload.get("public_api"), dict) else {}
    configured_backend_api_url = str(backend_api.get("url") or get_runtime_backend_api_url()).strip()
    configured_public_api_url = str(public_api.get("url") or payload.get("apiBaseUrl") or get_runtime_public_api_url()).strip()
    request_public_api_url = str(request.base_url).rstrip("/")
    public_api_url = configured_public_api_url or request_public_api_url
    backend_api_url = configured_backend_api_url or public_api_url
    payload.update({
        "backend_url": public_api_url,
        "backendApiUrl": backend_api_url,
        "backend_api_url": backend_api_url,
        "tenant_id": SINGLE_TENANT_ID,
        "auth_required": False,
        "apiBaseUrl": public_api_url,
        "publicApiUrl": public_api_url,
        "public_api_url": public_api_url,
        "backend_api": {
            **backend_api,
            "url": backend_api_url,
            "token": str(backend_api.get("api_token") or backend_api.get("token") or ""),
        },
        "public_api": {
            **public_api,
            "url": public_api_url,
            "token": str(public_api.get("api_token") or public_api.get("token") or ""),
        },
        "backendApi": {
            **(payload.get("backendApi") if isinstance(payload.get("backendApi"), dict) else {}),
            "url": backend_api_url,
            "apiToken": str(backend_api.get("api_token") or backend_api.get("token") or ""),
            "token": str(backend_api.get("api_token") or backend_api.get("token") or ""),
        },
        "publicApi": {
            **(payload.get("publicApi") if isinstance(payload.get("publicApi"), dict) else {}),
            "url": public_api_url,
            "apiToken": str(public_api.get("api_token") or public_api.get("token") or ""),
            "token": str(public_api.get("api_token") or public_api.get("token") or ""),
        },
    })
    return payload


@app.post("/api/config")
def save_public_api_config(payload: PublicApiConfigPayload, _: None = Depends(require_admin_context)):
    save_api_config(
        payload.apiBaseUrl,
        backend_api=payload.backendApi.model_dump() if payload.backendApi else None,
        public_api=payload.publicApi.model_dump() if payload.publicApi else None,
    )
    return build_public_api_config()
