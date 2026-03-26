from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api_config import build_public_api_config, ensure_api_config_storage, save_api_config
from app.auth import require_role
from app.backup import ensure_backup_storage, start_backup_scheduler, stop_backup_scheduler
from app.branding_engine import BRANDING_CDN_ROOT, BRANDING_STORAGE_ROOT, ensure_branding_storage
from app.logo_utils import STATIC_ROOT, ensure_static_logo_storage
from app.notifications import start_notification_scheduler, stop_notification_scheduler
from app.mobile_builder import ensure_mobile_builder_storage, start_mobile_build_worker, stop_mobile_build_worker
from app.routes.admin_accounts import router as admin_accounts_router
from app.routes.admin_auth import router as admin_auth_router
from app.routes.admin import router as admin_router
from app.routes.analytics import router as analytics_router
from app.routes.auth_login import router as auth_login_router
from app.routes.config import router as config_router
from app.routes.device import router as device_router
from app.routes.football import router as football_router
from app.routes.football_data import router as football_data_router
from app.routes.license import router as license_router
from app.routes.mobile_builder import router as mobile_builder_router
from app.routes.playback import router as playback_router
from app.routes.provider import router as provider_router
from app.routes.streams import router as streams_router
from app.routes.tenant import router as tenant_router
from app.routes.updates import router as updates_router
from app.routes.version import router as version_router
from app.routes.viewer import router as viewer_router
from app.settings import is_development_mode, load_backup_settings_from_env, load_email_settings_from_env, load_settings_from_env, validate_settings
from app.storage import ASSETS_DIR, ensure_storage_files, load_config, log_audit_event, save_config
from app.tenant_middleware import tenant_resolver
from app.update_service import ensure_update_storage

app = FastAPI(title="Football IPTV API")
DOWNLOADS_DIR = Path(__file__).resolve().parent / "downloads"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
ensure_storage_files()
ensure_backup_storage()
ensure_update_storage()
ensure_mobile_builder_storage()
ensure_branding_storage()
ensure_api_config_storage()
ensure_static_logo_storage()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*", "Authorization", "X-Api-Token", "X-Tenant-Id", "X-Device-Id", "X-Server-Id"],
    expose_headers=["*"],
    max_age=86400,
)
app.middleware("http")(tenant_resolver)

app.include_router(streams_router, prefix="/streams", tags=["streams"])
app.include_router(config_router, prefix="/config", tags=["config"])
app.include_router(auth_login_router)
app.include_router(admin_accounts_router, prefix="/admin", tags=["admin-accounts"])
app.include_router(admin_auth_router, prefix="/admin/auth", tags=["admin-auth"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(provider_router)
app.include_router(tenant_router, prefix="/tenant", tags=["tenant"])
app.include_router(device_router, prefix="/device", tags=["device"])
app.include_router(license_router, prefix="/license", tags=["license"])
app.include_router(viewer_router, prefix="/viewer", tags=["viewer"])
app.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
app.include_router(football_router)
app.include_router(football_data_router)
app.include_router(playback_router, tags=["playback"])
app.include_router(updates_router, prefix="/updates", tags=["updates"])
app.include_router(mobile_builder_router, prefix="/mobile", tags=["mobile-builder"])
app.include_router(version_router, tags=["version"])
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
app.mount("/downloads", StaticFiles(directory=DOWNLOADS_DIR), name="downloads")
app.mount("/branding", StaticFiles(directory=BRANDING_STORAGE_ROOT), name="branding")
app.mount("/cdn/branding", StaticFiles(directory=BRANDING_CDN_ROOT), name="branding-cdn")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)},
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"Incoming: {request.url}")
    response = await call_next(request)
    print(f"Response: {response.status_code}")
    return response


@app.middleware("http")
async def audit_request(request: Request, call_next):
    started = perf_counter()
    response = await call_next(request)
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
    start_mobile_build_worker()


@app.on_event("shutdown")
def shutdown_background_services() -> None:
    stop_backup_scheduler()
    stop_notification_scheduler()
    stop_mobile_build_worker()


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
def api_config():
    localhost_api = "http://localhost:8000" if is_development_mode() else str(build_public_api_config().get("apiBaseUrl") or "http://127.0.0.1:8000")
    payload = build_public_api_config()
    payload.update({
        "backend_url": localhost_api,
        "tenant_id": "master",
        "auth_required": False,
        "apiBaseUrl": localhost_api,
        "publicApiUrl": localhost_api,
        "public_api_url": localhost_api,
        "backend_api": {
            "url": localhost_api,
            "api_token": "",
            "connected": False,
            "token": "",
        },
        "public_api": {
            "url": localhost_api,
            "api_token": "",
            "connected": False,
            "token": "",
        },
        "backendApi": {
            "url": localhost_api,
            "apiToken": "",
            "connected": False,
            "token": "",
        },
        "publicApi": {
            "url": localhost_api,
            "apiToken": "",
            "connected": False,
            "token": "",
        },
    })
    return payload


@app.post("/api/config")
def save_public_api_config(payload: PublicApiConfigPayload, _: dict = Depends(require_role("master"))):
    save_api_config(
        payload.apiBaseUrl,
        backend_api=payload.backendApi.model_dump() if payload.backendApi else None,
        public_api=payload.publicApi.model_dump() if payload.publicApi else None,
    )
    return build_public_api_config()
