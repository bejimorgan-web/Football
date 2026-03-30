import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app.branding_engine import get_branding_response, process_logo_upload, rebuild_branding_assets
from app.storage import (
    _normalize_tenant_id,
    authenticate_tenant_admin,
    create_tenant_access_token,
    get_branding_config,
    get_mobile_runtime_manifest,
    list_mobile_apps,
    get_tenant,
    list_tenants,
    update_tenant_branding,
    validate_admin_api_token,
    validate_tenant_access_token,
)

router = APIRouter()
logger = logging.getLogger("football_iptv.tenant")


def _resolve_requested_tenant(
    authorization: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    requested_tenant_id = str(tenant_id or "").strip()
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = validate_tenant_access_token(token)
            resolved = str(payload.get("tenant_id") or "").strip()
            if requested_tenant_id and _normalize_tenant_id(requested_tenant_id) != _normalize_tenant_id(resolved):
                logger.warning(
                    "Token tenant %s does not match request tenant %s for tenant route",
                    _normalize_tenant_id(resolved),
                    _normalize_tenant_id(requested_tenant_id),
                )
                raise HTTPException(status_code=401, detail="Token tenant does not match requested tenant.")
            if resolved:
                return resolved
        except ValueError:
            try:
                admin = validate_admin_api_token(token, require_server=False)
            except ValueError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            admin_tenant_id = str(admin.get("tenant_id") or "").strip()
            if requested_tenant_id and _normalize_tenant_id(requested_tenant_id) != _normalize_tenant_id(admin_tenant_id):
                logger.warning(
                    "Token tenant %s does not match request tenant %s for tenant route",
                    _normalize_tenant_id(admin_tenant_id),
                    _normalize_tenant_id(requested_tenant_id),
                )
                raise HTTPException(status_code=401, detail="Token tenant does not match requested tenant.")
            if admin_tenant_id:
                return admin_tenant_id
    if requested_tenant_id:
        return requested_tenant_id
    raise HTTPException(status_code=400, detail="tenant_id is required.")


def _resolve_authenticated_tenant(
    authorization: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    return _resolve_requested_tenant(authorization, tenant_id)


class BrandingLogoPayload(BaseModel):
    data_url: str


class TenantLoginPayload(BaseModel):
    tenant_id: str
    username: str
    password: str


@router.post("/login")
def tenant_login(payload: TenantLoginPayload):
    logger.info("Tenant login requested for tenant_id=%s username=%s", payload.tenant_id, payload.username)
    try:
        tenant = authenticate_tenant_admin(payload.tenant_id, payload.username, payload.password)
        token = create_tenant_access_token(str(tenant.get("tenant_id") or ""), payload.username)
    except ValueError as exc:
        logger.warning(
            "Tenant login failed for tenant_id=%s username=%s: %s",
            payload.tenant_id,
            payload.username,
            str(exc),
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    logger.info(
        "Tenant login succeeded for tenant_id=%s username=%s",
        str(tenant.get("tenant_id") or ""),
        payload.username,
    )
    return {
        "token": token["token"],
        "expires_at": token["expires_at"],
        "tenant": get_branding_config(str(tenant.get("tenant_id") or "")),
    }


@router.get("/profile")
def tenant_profile(
    authorization: Optional[str] = Header(default=None),
    tenant_id: Optional[str] = Query(None),
):
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = validate_tenant_access_token(token)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {"tenant": get_branding_config(str(payload.get("tenant_id") or "")), "auth": payload}

    if tenant_id:
        try:
            return {"tenant": get_branding_config(tenant_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "items": [
            {
                "tenant_id": item.get("tenant_id"),
                "name": item.get("name"),
                "branding": item.get("branding"),
            }
            for item in list_tenants()
        ]
    }


@router.get("/mobile-config")
def tenant_mobile_config(
    authorization: Optional[str] = Header(default=None),
    tenant_id: Optional[str] = Query(None),
):
    resolved_tenant_id = _resolve_requested_tenant(authorization, tenant_id)
    try:
        tenant = get_branding_config(resolved_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    branding = tenant.get("branding") if isinstance(tenant.get("branding"), dict) else {}
    return {
        "tenant_id": tenant.get("tenant_id"),
        "app_name": str(branding.get("app_name") or tenant.get("name") or ""),
        "logo_url": str(branding.get("logo_url") or branding.get("logo_file") or ""),
        "theme_color": str(branding.get("primary_color") or ""),
        "secondary_color": str(branding.get("secondary_color") or branding.get("accent_color") or ""),
        "server_url": str(tenant.get("backend_url") or branding.get("server_url") or branding.get("api_base_url") or ""),
        "server_url_source": str(tenant.get("backend_url_source") or "configured"),
        "server_url_notice": str(tenant.get("backend_url_notice") or ""),
        "splash_screen": str(branding.get("splash_screen") or ""),
        "language": tenant.get("language") or {},
        "feature_flags": tenant.get("feature_flags") or {},
        "update_manifest": get_mobile_runtime_manifest(resolved_tenant_id),
    }


@router.get("/mobile-apps")
def tenant_mobile_apps(
    authorization: Optional[str] = Header(default=None),
    tenant_id: Optional[str] = Query(None),
):
    resolved_tenant_id = _resolve_requested_tenant(authorization, tenant_id)
    return {"items": list_mobile_apps(tenant_id=resolved_tenant_id)}


@router.get("/branding")
def tenant_branding(
    authorization: Optional[str] = Header(default=None),
    tenant_id: Optional[str] = Query(None),
):
    resolved_tenant_id = _resolve_requested_tenant(authorization, tenant_id)
    tenant = get_branding_config(resolved_tenant_id)
    branding = tenant.get("branding") if isinstance(tenant.get("branding"), dict) else {}
    return get_branding_response(
        resolved_tenant_id,
        app_name=str(branding.get("app_name") or tenant.get("name") or ""),
        logo_url=str(branding.get("logo_url") or branding.get("logo_file") or ""),
        primary_color=str(branding.get("primary_color") or "#11B37C"),
        secondary_color=str(branding.get("secondary_color") or branding.get("accent_color") or "#7EE3AF"),
    )


@router.post("/branding/upload-logo")
def tenant_branding_upload_logo(
    payload: BrandingLogoPayload,
    authorization: Optional[str] = Header(default=None),
    tenant_id: Optional[str] = Query(None),
):
    resolved_tenant_id = _resolve_authenticated_tenant(authorization, tenant_id)
    tenant = get_branding_config(resolved_tenant_id)
    branding = tenant.get("branding") if isinstance(tenant.get("branding"), dict) else {}
    try:
        generated = process_logo_upload(
            resolved_tenant_id,
            data_url=payload.data_url,
            app_name=str(branding.get("app_name") or tenant.get("name") or ""),
            primary_color=str(branding.get("primary_color") or "#11B37C"),
            secondary_color=str(branding.get("secondary_color") or branding.get("accent_color") or "#7EE3AF"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    update_tenant_branding(
        resolved_tenant_id,
        {
            "logo_url": str(generated.get("logo_storage_path") or ""),
            "logo_file": str(generated.get("logo_storage_path") or ""),
            "icon_url": str(generated.get("desktop_icon_path") or ""),
            "splash_screen": str(generated.get("splash_screen_path") or ""),
            "favicon_path": str(generated.get("favicon_path") or ""),
            "desktop_icon_path": str(generated.get("desktop_icon_path") or ""),
            "mobile_icon_path": str(generated.get("mobile_icon_path") or ""),
        },
    )
    return generated


@router.post("/branding/rebuild-assets")
def tenant_branding_rebuild_assets(
    authorization: Optional[str] = Header(default=None),
    tenant_id: Optional[str] = Query(None),
):
    resolved_tenant_id = _resolve_authenticated_tenant(authorization, tenant_id)
    tenant = get_branding_config(resolved_tenant_id)
    branding = tenant.get("branding") if isinstance(tenant.get("branding"), dict) else {}
    try:
        generated = rebuild_branding_assets(
            resolved_tenant_id,
            app_name=str(branding.get("app_name") or tenant.get("name") or ""),
            primary_color=str(branding.get("primary_color") or "#11B37C"),
            secondary_color=str(branding.get("secondary_color") or branding.get("accent_color") or "#7EE3AF"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    update_tenant_branding(
        resolved_tenant_id,
        {
            "logo_url": str(generated.get("logo_storage_path") or branding.get("logo_url") or branding.get("logo_file") or ""),
            "logo_file": str(generated.get("logo_storage_path") or branding.get("logo_file") or ""),
            "icon_url": str(generated.get("desktop_icon_path") or ""),
            "splash_screen": str(generated.get("splash_screen_path") or ""),
            "favicon_path": str(generated.get("favicon_path") or ""),
            "desktop_icon_path": str(generated.get("desktop_icon_path") or ""),
            "mobile_icon_path": str(generated.get("mobile_icon_path") or ""),
        },
    )
    return generated
