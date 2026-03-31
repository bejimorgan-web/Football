from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.auth import get_current_user, require_admin_context, require_role
from app.backup import create_backup, get_backup_status
from app.branding_engine import get_branding_response, process_logo_upload, rebuild_branding_assets
from app.services.iptv import IPTVAuthError, IPTVProviderError, get_cache_info, list_streams
from app.services.provider_parser import normalize_groups
from app.settings import (
    IPTVSettings,
    load_backup_settings_from_env,
    validate_settings,
)
from app.storage import (
    authenticate_tenant_admin,
    approve_stream_mapping,
    block_platform_client,
    block_user,
    check_for_desktop_update,
    delete_platform_client,
    delete_club,
    delete_competition,
    delete_nation,
    extend_platform_client_trial_days,
    extend_user_expiry_days,
    enrich_approved_streams,
    get_branding_config,
    get_install_stats,
    get_mobile_app,
    get_platform_client_dashboard,
    get_platform_client_stats,
    get_provider_record,
    extend_subscription,
    get_approved_streams,
    get_security_dashboard,
    get_tenant,
    get_user_stats,
    grant_free_access,
    list_clubs,
    list_competitions,
    list_group_channels,
    list_nations,
    list_platform_clients,
    list_tenants,
    list_online_users,
    list_provider_groups,
    list_provider_records,
    list_users,
    load_provider_settings,
    load_tenant_meta,
    mark_setup_completed,
    remove_approved_stream,
    remove_free_access,
    register_admin_server,
    load_release_info,
    reset_platform_client_server_binding,
    reset_user_device,
    reset_admin_server,
    rename_user,
    restore_user_name,
    save_branding_asset,
    list_apk_versions,
    save_provider_settings,
    save_uploaded_logo,
    set_latest_apk_version,
    set_user_vpn_policy,
    get_setup_status,
    sync_provider_catalog,
    transfer_admin_device,
    unblock_platform_client,
    unblock_user,
    upload_apk_version,
    update_tenant_branding,
    upsert_club,
    upsert_competition,
    upsert_nation,
    upsert_tenant,
)
router = APIRouter()


class NationPayload(BaseModel):
    id: Optional[str] = None
    name: str
    logo_url: Optional[str] = ""


class CompetitionPayload(BaseModel):
    id: Optional[str] = None
    name: str
    nation_id: str
    type: str = "league"
    participant_type: str = "club"
    club_ids: List[str] = []
    logo_url: Optional[str] = ""


class ClubPayload(BaseModel):
    id: Optional[str] = None
    name: str
    nation_id: Optional[str] = None
    logo_url: Optional[str] = ""


class LogoUploadPayload(BaseModel):
    folder: str
    name_hint: str
    data_url: str


class BrandingAssetPayload(BaseModel):
    data_url: str


class ApproveStreamPayload(BaseModel):
    stream_id: str
    nation_id: str
    competition_id: str
    home_club_id: str
    away_club_id: str
    kickoff_label: Optional[str] = ""


class DeviceActionPayload(BaseModel):
    device_id: str


class RenameUserPayload(BaseModel):
    device_id: str
    admin_name: str


class ExtendSubscriptionPayload(BaseModel):
    device_id: str
    plan: str


class ExtendUserPayload(BaseModel):
    device_id: str
    plan: Optional[str] = None
    days: Optional[int] = None


class VpnPolicyPayload(BaseModel):
    device_id: str
    policy: str


class BrandingPayload(BaseModel):
    app_name: Optional[str] = None
    package_name: Optional[str] = None
    logo_url: Optional[str] = None
    logo_file: Optional[str] = None
    icon_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    surface_color: Optional[str] = None
    background_color: Optional[str] = None
    text_color: Optional[str] = None
    api_base_url: Optional[str] = None
    server_url: Optional[str] = None
    splash_screen: Optional[str] = None


class SubscriptionPlanPayload(BaseModel):
    id: str
    name: str
    duration_days: int
    price_label: Optional[str] = "Contact Admin"


class TenantPayload(BaseModel):
    tenant_id: Optional[str] = None
    name: str
    email: Optional[str] = ""
    subscription_plan: Optional[str] = "trial"
    license_key: Optional[str] = ""
    server_ip: Optional[str] = ""
    status: Optional[str] = "active"
    backend_url: Optional[str] = ""
    admin_username: Optional[str] = ""
    admin_password: Optional[str] = ""
    trial_days: Optional[int] = 3
    subscription_plans: Optional[list[SubscriptionPlanPayload]] = None
    branding: Optional[BrandingPayload] = None


class BackupRunResponse(BaseModel):
    status: str
    archive_path: Optional[str] = None
    backup_dir: str
    error: Optional[str] = None

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


class ValidateDevicePayload(BaseModel):
    api_token: str
    device_id: str
    server_id: str


class UpdateCheckPayload(BaseModel):
    current_version: str
    platform: Optional[str] = ""


class TrialDaysPayload(BaseModel):
    days: int = 3


class UploadApkPayload(BaseModel):
    version: str
    filename: str
    file_data: str


class SetLatestApkPayload(BaseModel):
    force_update: bool = False


def _settings_to_dict(settings: IPTVSettings) -> dict:
    if hasattr(settings, "model_dump"):
        return settings.model_dump()
    return settings.dict()
router.dependencies.append(Depends(require_admin_context))
ADMIN_ACCESS = Depends(require_role("master", "client"))
MASTER_ACCESS = Depends(require_role("master"))


def _scoped_tenant_id(request: Request, tenant_id: Optional[str]) -> str:
    context = getattr(request.state, "admin_context", {"scope": "platform", "tenant_id": None})
    if context.get("scope") in {"tenant", "admin"}:
        if str(context.get("role") or "").strip().lower() == "master":
            return str(tenant_id or context.get("tenant_id") or "default")
        token_tenant_id = str(context.get("tenant_id") or "")
        if tenant_id and tenant_id != token_tenant_id:
            raise HTTPException(status_code=403, detail="Tenant token cannot access another tenant.")
        return token_tenant_id
    return str(tenant_id or "default")


def _scoped_admin_id(request: Request) -> Optional[str]:
    context = getattr(request.state, "admin_context", {"scope": "platform", "admin_id": None})
    return str(context.get("admin_id") or "").strip() or None


def _require_settings(request: Request, tenant_id: Optional[str] = None) -> IPTVSettings:
    settings = load_provider_settings(admin_id=_scoped_admin_id(request), tenant_id=_scoped_tenant_id(request, tenant_id))
    if settings is None:
        raise HTTPException(status_code=503, detail="Backend is not configured.")
    return settings


def _load_provider_streams(request: Request, tenant_id: Optional[str] = None, force_refresh: bool = False):
    settings = load_provider_settings(admin_id=_scoped_admin_id(request), tenant_id=_scoped_tenant_id(request, tenant_id))
    if settings is None:
        return []
    try:
        return list_streams(settings=settings, force_refresh=force_refresh)
    except IPTVAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except IPTVProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def get_active_providers(admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    settings = load_provider_settings(admin_id=admin_id, tenant_id=tenant_id)
    if settings is None:
        return []
    records = list_provider_records(admin_id=admin_id, tenant_id=tenant_id)
    if records:
        return [item for item in records if bool(item.get("active"))]
    settings_payload = _settings_to_dict(settings)
    return [{
        "provider_id": "active",
        "id": "active",
        "name": (
            str(settings_payload.get("m3u_playlist_url") or "").strip()
            or str(settings_payload.get("xtream_server_url") or "").strip()
            or "Active Provider"
        ),
        "type": "m3u" if settings_payload.get("m3u_playlist_url") else "xtream",
        "active": True,
        "status": "active",
    }]


def get_provider_groups(provider_id: str, streams: List[Dict[str, object]], provider_active: bool = True, *, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    if not provider_active:
        return []
    sync_provider_catalog(provider_id=provider_id, streams=streams, admin_id=admin_id, tenant_id=tenant_id)
    return list_provider_groups(provider_id=provider_id, admin_id=admin_id, tenant_id=tenant_id)


def get_group_channels(group_id: str, streams: List[Dict[str, object]], provider_active: bool = True, *, provider_id: str = "active", admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    if not provider_active:
        return []
    sync_provider_catalog(provider_id=provider_id, streams=streams, admin_id=admin_id, tenant_id=tenant_id)
    return list_group_channels(group_id=group_id, provider_id=provider_id, admin_id=admin_id, tenant_id=tenant_id)


def _handle_user_mutation(action, *args):
    try:
        item = action(*args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tenant_id = args[-1] if args else None
    return {"item": item, "stats": get_user_stats(tenant_id=tenant_id if isinstance(tenant_id, str) else None)}


@router.get("/config")
def get_config(request: Request, tenant_id: Optional[str] = Query(None)):
    settings = load_provider_settings(admin_id=_scoped_admin_id(request), tenant_id=_scoped_tenant_id(request, tenant_id))
    if settings is None:
        return {"configured": False, "settings": None}
    return {"configured": True, "settings": _settings_to_dict(settings)}


@router.post("/config")
def set_config(settings: IPTVSettings, request: Request, tenant_id: Optional[str] = Query(None)):
    ok, message = validate_settings(settings)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    save_provider_settings(settings, admin_id=_scoped_admin_id(request), tenant_id=_scoped_tenant_id(request, tenant_id))
    return {"configured": True, "settings": _settings_to_dict(settings)}


@router.get("/status")
def admin_status(request: Request, tenant_id: Optional[str] = Query(None)):
    settings = load_provider_settings(admin_id=_scoped_admin_id(request), tenant_id=_scoped_tenant_id(request, tenant_id))
    cache = get_cache_info()
    backup_status = get_backup_status(load_backup_settings_from_env())
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    return {
        "configured": settings is not None,
        "cache": cache,
        "user_stats": get_user_stats(tenant_id=scoped_tenant_id),
        "backup": {
            "schedule": backup_status.get("configured_schedule"),
            "backup_path": backup_status.get("backup_path"),
            "last_backup": backup_status.get("last_backup"),
        },
        "tenant": get_branding_config(scoped_tenant_id),
    }


@router.post("/register-server")
def admin_register_server_binding(payload: ServerRegisterPayload, _: dict = ADMIN_ACCESS):
    try:
        return {"admin": register_admin_server(**payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset-server")
def admin_reset_server_binding(payload: ServerResetPayload, _: dict = ADMIN_ACCESS):
    try:
        return {"admin": reset_admin_server(**payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transfer-device")
def admin_transfer_bound_device(payload: DeviceTransferPayload, _: dict = ADMIN_ACCESS):
    try:
        return transfer_admin_device(api_token=payload.api_token, next_device_id=payload.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/validate-device")
def admin_validate_device_binding(payload: ValidateDevicePayload, _: dict = Depends(get_current_user)):
    try:
        from app.storage import validate_admin_api_token

        admin = validate_admin_api_token(
            payload.api_token,
            device_id=payload.device_id,
            server_id=payload.server_id,
            require_server=True,
        )
        return {
            "valid": True,
            "admin_id": admin.get("admin_id"),
            "tenant_id": admin.get("tenant_id"),
            "device_id": admin.get("device_id"),
            "server_id": admin.get("server_id"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/platform_clients/dashboard")
def admin_platform_clients_dashboard(request: Request, _: dict = MASTER_ACCESS):
    del request
    return get_platform_client_dashboard()


@router.get("/apk-versions")
def admin_list_apk_versions(_: dict = MASTER_ACCESS):
    return {
        "items": list_apk_versions(),
    }


@router.post("/upload-apk")
def admin_upload_apk(payload: UploadApkPayload, _: dict = MASTER_ACCESS):
    try:
        item = upload_apk_version(version=payload.version, filename=payload.filename, file_data=payload.file_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "uploaded",
        "item": item,
        "items": list_apk_versions(),
    }


@router.post("/apk-versions/{apk_id}/set-latest")
def admin_set_latest_apk(apk_id: str, payload: SetLatestApkPayload, _: dict = MASTER_ACCESS):
    try:
        item = set_latest_apk_version(apk_id, force_update=payload.force_update)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "updated",
        "item": item,
        "items": list_apk_versions(),
    }


@router.get("/platform_clients/analytics")
def admin_platform_clients_analytics(_: dict = MASTER_ACCESS):
    stats = get_install_stats()
    dashboard = get_platform_client_dashboard()
    return {
        "summary": stats["totals"],
        "items": stats["items"],
        "subscriptions": dashboard["subscriptions"],
        "release": load_release_info(),
    }


@router.post("/platform_clients/update_check")
def admin_platform_clients_update_check(payload: UpdateCheckPayload, _: dict = ADMIN_ACCESS):
    return check_for_desktop_update(payload.current_version, platform=payload.platform or "")


@router.get("/white_label/installs")
def admin_white_label_installs_alias(request: Request, _: dict = MASTER_ACCESS):
    return admin_platform_clients_dashboard(request)


@router.get("/white_label/subscriptions")
def admin_white_label_subscriptions_alias(_: dict = MASTER_ACCESS):
    return admin_platform_clients_analytics()


@router.post("/white_label/update_check")
def admin_white_label_update_check_alias(payload: UpdateCheckPayload, _: dict = ADMIN_ACCESS):
    return admin_platform_clients_update_check(payload)


@router.get("/platform_clients")
def admin_list_platform_clients(_: dict = MASTER_ACCESS):
    return {
        "items": list_platform_clients(),
        "stats": get_platform_client_stats(),
    }


@router.post("/platform_clients/{admin_id}/block")
def admin_block_platform_client(admin_id: str, _: dict = MASTER_ACCESS):
    try:
        return {"item": block_platform_client(admin_id), "stats": get_platform_client_stats()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/platform_clients/{admin_id}/unblock")
def admin_unblock_platform_client(admin_id: str, _: dict = MASTER_ACCESS):
    try:
        return {"item": unblock_platform_client(admin_id), "stats": get_platform_client_stats()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/platform_clients/{admin_id}/extend_trial")
def admin_extend_platform_client_trial(admin_id: str, payload: TrialDaysPayload, _: dict = MASTER_ACCESS):
    try:
        return {"item": extend_platform_client_trial_days(admin_id, payload.days), "stats": get_platform_client_stats()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/platform_clients/{admin_id}/reset_server")
def admin_reset_platform_client_server(admin_id: str, _: dict = MASTER_ACCESS):
    try:
        return {"item": reset_platform_client_server_binding(admin_id), "stats": get_platform_client_stats()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/platform_clients/{admin_id}")
def admin_delete_platform_client_account(admin_id: str, _: dict = MASTER_ACCESS):
    try:
        result = delete_platform_client(admin_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "stats": get_platform_client_stats()}


@router.get("/setup-status")
def admin_setup_status(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return get_setup_status(admin_id=_scoped_admin_id(request), tenant_id=_scoped_tenant_id(request, tenant_id))


@router.post("/setup-complete")
def admin_setup_complete(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return mark_setup_completed(admin_id=_scoped_admin_id(request), tenant_id=_scoped_tenant_id(request, tenant_id))


@router.post("/refresh")
def refresh_streams(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    streams = _load_provider_streams(request, tenant_id=tenant_id, force_refresh=True)
    return {"status": "refreshed", "total": len(streams)}


@router.post("/assets/upload")
def upload_asset(payload: LogoUploadPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    try:
        logo_url = save_uploaded_logo(
            data_url=payload.data_url,
            folder=payload.folder,
            name_hint=payload.name_hint,
            tenant_id=_scoped_tenant_id(request, tenant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"url": logo_url}


def _save_branding_asset(request: Request, asset_kind: str, payload: BrandingAssetPayload, tenant_id: Optional[str]) -> Dict[str, object]:
    admin_id = _scoped_admin_id(request)
    if not admin_id:
        raise HTTPException(status_code=403, detail="Admin identity required.")
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    current_branding = get_branding_config(scoped_tenant_id)
    branding_payload = current_branding.get("branding") if isinstance(current_branding.get("branding"), dict) else {}
    try:
        if asset_kind == "logo":
            generated = process_logo_upload(
                scoped_tenant_id,
                data_url=payload.data_url,
                app_name=str(branding_payload.get("app_name") or current_branding.get("name") or ""),
                primary_color=str(branding_payload.get("primary_color") or "#11B37C"),
                secondary_color=str(branding_payload.get("secondary_color") or branding_payload.get("accent_color") or "#7EE3AF"),
            )
            asset_url = str(generated.get("logo_storage_path") or "")
        else:
            asset_url = save_branding_asset(admin_id=admin_id, asset_kind=asset_kind, data_url=payload.data_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    update_payload = (
        {
            "logo_url": asset_url,
            "logo_file": asset_url,
            "icon_url": str(generated.get("desktop_icon_path") or ""),
            "splash_screen": str(generated.get("splash_screen_path") or ""),
            "favicon_path": str(generated.get("favicon_path") or ""),
            "desktop_icon_path": str(generated.get("desktop_icon_path") or ""),
            "mobile_icon_path": str(generated.get("mobile_icon_path") or ""),
        }
        if asset_kind == "logo"
        else {"icon_url": asset_url}
        if asset_kind == "icon"
        else {"splash_screen": asset_url}
    )
    branding = update_tenant_branding(scoped_tenant_id, update_payload)
    return {"url": asset_url, "branding": branding.get("branding", {})}


@router.post("/branding/upload_logo")
def admin_upload_logo(payload: BrandingAssetPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _save_branding_asset(request, "logo", payload, tenant_id)


@router.post("/branding/upload_icon")
def admin_upload_icon(payload: BrandingAssetPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _save_branding_asset(request, "icon", payload, tenant_id)


@router.post("/branding/upload_splash")
def admin_upload_splash(payload: BrandingAssetPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _save_branding_asset(request, "splash", payload, tenant_id)


@router.get("/nations")
def admin_nations(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return {"items": list_nations(tenant_id=_scoped_tenant_id(request, tenant_id))}


@router.post("/nations")
def create_or_update_nation(payload: NationPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    try:
        item = upsert_nation(
            nation_id=payload.id,
            name=payload.name,
            logo_url=payload.logo_url or "",
            tenant_id=_scoped_tenant_id(request, tenant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/nations/{nation_id}")
def remove_nation(nation_id: str, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    try:
        delete_nation(nation_id, tenant_id=_scoped_tenant_id(request, tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "nation_id": nation_id}


@router.get("/competitions")
def admin_competitions(request: Request, nation_id: Optional[str] = None, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return {"items": list_competitions(nation_id=nation_id, tenant_id=_scoped_tenant_id(request, tenant_id))}


@router.post("/competitions")
def create_or_update_competition(payload: CompetitionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    try:
        item = upsert_competition(
            competition_id=payload.id,
            name=payload.name,
            nation_id=payload.nation_id,
            competition_type=payload.type,
            participant_type=payload.participant_type,
            club_ids=payload.club_ids,
            logo_url=payload.logo_url or "",
            tenant_id=_scoped_tenant_id(request, tenant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/competitions/{competition_id}")
def remove_competition(competition_id: str, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    try:
        delete_competition(competition_id, tenant_id=_scoped_tenant_id(request, tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "competition_id": competition_id}


@router.get("/clubs")
def admin_clubs(
    request: Request,
    nation_id: Optional[str] = None,
    competition_id: Optional[str] = None,
    tenant_id: Optional[str] = Query(None),
    _: dict = ADMIN_ACCESS,
):
    return {"items": list_clubs(nation_id=nation_id, competition_id=competition_id, tenant_id=_scoped_tenant_id(request, tenant_id))}


@router.post("/clubs")
def create_or_update_club(payload: ClubPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    try:
        item = upsert_club(
            club_id=payload.id,
            name=payload.name,
            nation_id=payload.nation_id,
            logo_url=payload.logo_url or "",
            tenant_id=_scoped_tenant_id(request, tenant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/clubs/{club_id}")
def remove_club(club_id: str, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    try:
        delete_club(club_id, tenant_id=_scoped_tenant_id(request, tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "club_id": club_id}


@router.get("/streams")
def admin_provider_streams(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    streams = _load_provider_streams(request, tenant_id=tenant_id, force_refresh=False)
    scoped_admin_id = _scoped_admin_id(request)
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    active_providers = get_active_providers(admin_id=scoped_admin_id, tenant_id=scoped_tenant_id)
    selected_provider_id = str(request.query_params.get("provider_id") or "active")
    provider_active = any(str(item.get("provider_id") or item.get("id") or "") == selected_provider_id and bool(item.get("active")) for item in active_providers)
    groups = get_provider_groups(selected_provider_id, streams, provider_active=provider_active, admin_id=scoped_admin_id, tenant_id=scoped_tenant_id) if provider_active else []
    channels = []
    if provider_active:
        selected_group_id = str(request.query_params.get("group_id") or "").strip()
        if selected_group_id:
            channels = get_group_channels(selected_group_id, streams, provider_active=True, provider_id=selected_provider_id, admin_id=scoped_admin_id, tenant_id=scoped_tenant_id)
    normalized_groups = normalize_groups(groups, channels or [
        {
            **item,
            "group_id": item.get("group_id") or next(
                (
                    str(group.get("group_id") or group.get("id") or "")
                    for group in groups
                    if str(group.get("name") or group.get("group_name") or "").strip() == str(item.get("group") or "Ungrouped").strip()
                ),
                "",
            ),
        }
        for item in streams
    ])
    approved_ids = {
        str(item.get("stream_id")): item for item in get_approved_streams(tenant_id=scoped_tenant_id) if item.get("stream_id")
    }
    items = [
        {
            **stream,
            "approved": str(stream.get("id")) in approved_ids,
            "approval": approved_ids.get(str(stream.get("id"))),
        }
        for stream in streams
    ]
    return {
        "items": items,
        "total": len(items),
        "providers": active_providers,
        "selectedProviderId": selected_provider_id,
        "groups": normalized_groups,
        "channels": channels,
    }


@router.get("/provider-groups")
def admin_provider_groups(request: Request, provider_id: str = Query("active"), tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    scoped_admin_id = _scoped_admin_id(request)
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    active_providers = get_active_providers(admin_id=scoped_admin_id, tenant_id=scoped_tenant_id)
    provider_active = any(str(item.get("provider_id") or item.get("id") or "") == str(provider_id or "") and bool(item.get("active")) for item in active_providers)
    streams = _load_provider_streams(request, tenant_id=tenant_id, force_refresh=False) if provider_active else []
    return {"items": get_provider_groups(provider_id, streams, provider_active=provider_active, admin_id=scoped_admin_id, tenant_id=scoped_tenant_id)}


@router.get("/provider-groups/{group_id}/channels")
def admin_provider_group_channels(
    group_id: str,
    request: Request,
    provider_id: str = Query("active"),
    tenant_id: Optional[str] = Query(None),
    _: dict = ADMIN_ACCESS,
):
    scoped_admin_id = _scoped_admin_id(request)
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    active_providers = get_active_providers(admin_id=scoped_admin_id, tenant_id=scoped_tenant_id)
    provider_active = any(str(item.get("provider_id") or item.get("id") or "") == str(provider_id or "") and bool(item.get("active")) for item in active_providers)
    streams = _load_provider_streams(request, tenant_id=tenant_id, force_refresh=False) if provider_active else []
    return {"items": get_group_channels(group_id, streams, provider_active=provider_active, provider_id=provider_id, admin_id=scoped_admin_id, tenant_id=scoped_tenant_id)}


@router.get("/streams/approved")
def admin_approved_streams(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    streams = _load_provider_streams(request, tenant_id=tenant_id, force_refresh=False)
    return {"items": enrich_approved_streams(streams, tenant_id=_scoped_tenant_id(request, tenant_id))}


@router.post("/streams/approve")
def admin_approve_stream(payload: ApproveStreamPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    streams = _load_provider_streams(request, tenant_id=tenant_id, force_refresh=False)
    stream = next(
        (item for item in streams if str(item.get("id")) == str(payload.stream_id)),
        None,
    )
    if stream is None:
        raise HTTPException(status_code=404, detail="Stream not found.")

    try:
        mapping = approve_stream_mapping(
            stream=stream,
            nation_id=payload.nation_id,
            competition_id=payload.competition_id,
            home_club_id=payload.home_club_id,
            away_club_id=payload.away_club_id,
            kickoff_label=payload.kickoff_label or "",
            tenant_id=_scoped_tenant_id(request, tenant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "approved", "item": mapping}


@router.post("/streams/remove")
def admin_remove_stream(stream_id: str, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    remove_approved_stream(stream_id, tenant_id=_scoped_tenant_id(request, tenant_id))
    return {"status": "removed", "stream_id": stream_id}


@router.get("/users")
def admin_users(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    return {"items": list_users(tenant_id=scoped_tenant_id), "stats": get_user_stats(tenant_id=scoped_tenant_id)}


@router.get("/users/online")
def admin_online_users(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    return {"items": list_online_users(tenant_id=scoped_tenant_id), "stats": get_user_stats(tenant_id=scoped_tenant_id)}


@router.post("/users/block")
def admin_block_user(payload: DeviceActionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _handle_user_mutation(block_user, payload.device_id, _scoped_tenant_id(request, tenant_id))


@router.post("/users/unblock")
def admin_unblock_user(payload: DeviceActionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _handle_user_mutation(unblock_user, payload.device_id, _scoped_tenant_id(request, tenant_id))


@router.post("/users/free-access")
def admin_free_access(payload: DeviceActionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _handle_user_mutation(grant_free_access, payload.device_id, _scoped_tenant_id(request, tenant_id))


@router.post("/users/remove-free-access")
def admin_remove_free_access(payload: DeviceActionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _handle_user_mutation(remove_free_access, payload.device_id, _scoped_tenant_id(request, tenant_id))


@router.post("/users/extend-subscription")
def admin_extend_subscription(payload: ExtendSubscriptionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _handle_user_mutation(extend_subscription, payload.device_id, payload.plan, _scoped_tenant_id(request, tenant_id))


@router.post("/block")
def admin_block_user_alias(payload: DeviceActionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return admin_block_user(payload, request, tenant_id, _)


@router.post("/unblock")
def admin_unblock_user_alias(payload: DeviceActionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return admin_unblock_user(payload, request, tenant_id, _)


@router.post("/extend")
def admin_extend_user_alias(payload: ExtendUserPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    if payload.days is not None:
        return _handle_user_mutation(extend_user_expiry_days, payload.device_id, int(payload.days), scoped_tenant_id)
    return _handle_user_mutation(extend_subscription, payload.device_id, str(payload.plan or "6_months"), scoped_tenant_id)


@router.post("/users/rename")
def admin_rename_user(payload: RenameUserPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _handle_user_mutation(rename_user, payload.device_id, payload.admin_name, _scoped_tenant_id(request, tenant_id))


@router.post("/users/restore-name")
def admin_restore_name(payload: DeviceActionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _handle_user_mutation(restore_user_name, payload.device_id, _scoped_tenant_id(request, tenant_id))


@router.post("/users/reset-device")
def admin_reset_device(payload: DeviceActionPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _handle_user_mutation(reset_user_device, payload.device_id, _scoped_tenant_id(request, tenant_id))


@router.post("/users/set-vpn-policy")
def admin_set_vpn_policy(payload: VpnPolicyPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return _handle_user_mutation(set_user_vpn_policy, payload.device_id, payload.policy, _scoped_tenant_id(request, tenant_id))


@router.get("/security")
def admin_security_dashboard(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    return get_security_dashboard(tenant_id=_scoped_tenant_id(request, tenant_id))


@router.get("/tenants")
def admin_tenants(request: Request, current_user: dict = Depends(get_current_user)):
    if str(current_user.get("role") or "") == "client":
        return {"items": [get_tenant(current_user.get("tenant_id"))]}
    return {"items": list_tenants()}


@router.post("/tenants")
def admin_upsert_tenant(payload: TenantPayload, request: Request, _: dict = MASTER_ACCESS):
    del request
    item = upsert_tenant(
        tenant_id=payload.tenant_id,
        name=payload.name,
        email=payload.email or "",
        subscription_plan=payload.subscription_plan or "trial",
        license_key=payload.license_key or "",
        server_ip=payload.server_ip or "",
        status=payload.status or "active",
        branding=payload.branding.model_dump(exclude_none=True) if payload.branding else None,
        subscription_plans=[plan.model_dump() for plan in payload.subscription_plans] if payload.subscription_plans else None,
        trial_policy={"enabled": True, "duration_days": max(1, int(payload.trial_days or 3))},
        backend_url=payload.backend_url or "",
        admin_username=payload.admin_username or "",
        admin_password=payload.admin_password or "",
    )
    return {"item": item, "items": list_tenants()}


@router.get("/branding")
def admin_branding(request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    payload = get_branding_config(scoped_tenant_id)
    branding = payload.get("branding") if isinstance(payload.get("branding"), dict) else {}
    payload["tenant_branding"] = get_branding_response(
        scoped_tenant_id,
        app_name=str(branding.get("app_name") or payload.get("name") or ""),
        logo_url=str(branding.get("logo_url") or branding.get("logo_file") or ""),
        primary_color=str(branding.get("primary_color") or "#11B37C"),
        secondary_color=str(branding.get("secondary_color") or branding.get("accent_color") or "#7EE3AF"),
    )
    return payload


@router.post("/branding")
def admin_update_branding(payload: BrandingPayload, request: Request, tenant_id: Optional[str] = Query(None), _: dict = ADMIN_ACCESS):
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    item = update_tenant_branding(
        scoped_tenant_id,
        payload.model_dump(exclude_none=True),
    )
    branding = item.get("branding") if isinstance(item.get("branding"), dict) else {}
    tenant_branding = get_branding_response(
        scoped_tenant_id,
        app_name=str(branding.get("app_name") or item.get("name") or ""),
        logo_url=str(branding.get("logo_url") or branding.get("logo_file") or ""),
        primary_color=str(branding.get("primary_color") or "#11B37C"),
        secondary_color=str(branding.get("secondary_color") or branding.get("accent_color") or "#7EE3AF"),
    )
    if str(tenant_branding.get("logo_url") or ""):
        try:
            tenant_branding = rebuild_branding_assets(
                scoped_tenant_id,
                app_name=str(branding.get("app_name") or item.get("name") or ""),
                primary_color=str(branding.get("primary_color") or "#11B37C"),
                secondary_color=str(branding.get("secondary_color") or branding.get("accent_color") or "#7EE3AF"),
            )
            item = update_tenant_branding(
                scoped_tenant_id,
                {
                    "favicon_path": str(tenant_branding.get("favicon_path") or ""),
                    "desktop_icon_path": str(tenant_branding.get("desktop_icon_path") or ""),
                    "mobile_icon_path": str(tenant_branding.get("mobile_icon_path") or ""),
                    "splash_screen": str(tenant_branding.get("splash_screen_path") or branding.get("splash_screen") or ""),
                },
            )
        except ValueError:
            pass
    return {"item": item, "branding": item.get("branding", {}), "tenant_branding": tenant_branding}


@router.get("/backup/status")
def admin_backup_status(_: dict = ADMIN_ACCESS):
    return get_backup_status(load_backup_settings_from_env())


@router.post("/backup/run", response_model=BackupRunResponse)
def admin_run_backup(_: dict = ADMIN_ACCESS):
    return create_backup(load_backup_settings_from_env())


@router.get("/ui", response_class=HTMLResponse)
def admin_ui():
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Football IPTV Admin API</title>
  <style>
    body { background: #0b1220; color: #e6edf7; font-family: Arial, sans-serif; margin: 40px; }
    .card { background: #121c30; border: 1px solid #22304c; border-radius: 16px; padding: 24px; max-width: 860px; }
    h1 { margin-top: 0; }
    code { color: #7ce4b8; }
    li { margin: 8px 0; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Football IPTV Admin API</h1>
    <p>The richer football management workflow now lives in the Electron desktop app.</p>
    <p>Available admin API families:</p>
    <ul>
      <li><code>GET/POST /admin/config</code></li>
      <li><code>POST /admin/refresh</code></li>
      <li><code>GET/POST/DELETE /admin/nations</code></li>
      <li><code>GET/POST/DELETE /admin/competitions</code></li>
      <li><code>GET/POST/DELETE /admin/clubs</code></li>
      <li><code>POST /admin/assets/upload</code></li>
      <li><code>GET /admin/streams</code></li>
      <li><code>GET /admin/streams/approved</code></li>
      <li><code>POST /admin/streams/approve</code></li>
      <li><code>GET /admin/users</code></li>
      <li><code>GET /admin/users/online</code></li>
      <li><code>POST /admin/users/block</code></li>
      <li><code>POST /admin/users/unblock</code></li>
      <li><code>POST /admin/users/free-access</code></li>
      <li><code>POST /admin/users/remove-free-access</code></li>
      <li><code>POST /admin/users/extend-subscription</code></li>
      <li><code>POST /admin/users/rename</code></li>
      <li><code>POST /admin/users/restore-name</code></li>
      <li><code>POST /admin/users/reset-device</code></li>
      <li><code>POST /admin/users/set-vpn-policy</code></li>
      <li><code>GET /admin/security</code></li>
      <li><code>GET /admin/backup/status</code></li>
      <li><code>POST /admin/backup/run</code></li>
    </ul>
  </div>
</body>
</html>
        """
    )
