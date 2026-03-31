from __future__ import annotations

import base64
import logging
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote
from uuid import uuid4

from app.api_config import get_api_base_url
from app.logo_utils import normalize_logo_url
from app.settings import IPTVSettings
from app.update_service import (
    default_update_metadata,
    get_release_snapshot,
    save_release_snapshot,
    semver_key as update_semver_key,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ASSETS_DIR = DATA_DIR / "assets"
CONFIG_PATH = DATA_DIR / "config.json"
METADATA_PATH = DATA_DIR / "football_metadata.json"
APPROVED_STREAMS_PATH = DATA_DIR / "approved_streams.json"
USERS_PATH = DATA_DIR / "users.json"
VIEWERS_PATH = DATA_DIR / "viewers.json"
SESSIONS_PATH = DATA_DIR / "sessions.json"
SECURITY_LOGS_PATH = DATA_DIR / "security_logs.json"
TENANTS_PATH = DATA_DIR / "tenants.json"
ADMINS_PATH = DATA_DIR / "admins.json"
TENANT_DATA_DIR = DATA_DIR / "tenants"
INSTALL_LOGS_PATH = DATA_DIR / "install_logs.json"
SUBSCRIPTION_LOGS_PATH = DATA_DIR / "subscription_logs.json"
AUDIT_LOGS_PATH = DATA_DIR / "audit_logs.json"
EMAIL_LOGS_PATH = DATA_DIR / "email_logs.json"
RELEASE_INFO_PATH = DATA_DIR / "app_release.json"
LICENSES_PATH = DATA_DIR / "licenses.json"
MASTER_DATA_DIR = DATA_DIR / "master"
APK_VERSIONS_PATH = DATA_DIR / "apk_versions.json"
APP_DOWNLOADS_DIR = Path(__file__).resolve().parent / "downloads"

TRIAL_DAYS = 3
ONLINE_WINDOW_MINUTES = 10
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$")
_SUBSCRIPTION_PLAN_DELTAS = {
    "6_months": timedelta(days=183),
    "1_year": timedelta(days=365),
}
_SUBSCRIPTION_PLAN_REVENUE = {
    "trial": 0.0,
    "6_months": 99.0,
    "1_year": 179.0,
}
MAX_VIEWER_SESSIONS = 5000
MAX_SECURITY_LOGS = 2000
MAX_STREAM_SESSIONS = 500
MAX_AUDIT_LOGS = 10000
_AUDIT_LOG_BUFFER_LIMIT = 25
_ACTIVE_VIEWERS: Dict[str, Dict[str, object]] = {}
_AUDIT_LOG_BUFFER: List[Dict[str, object]] = []
STREAM_TOKEN_TTL_SECONDS = 60
PRIVATE_IP_PREFIXES = ("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "127.", "::1")
DEFAULT_TENANT_ID = "default"
MASTER_TENANT_ID = "master"
logger = logging.getLogger("football_iptv.storage")


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    TENANT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    MASTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    APP_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    for folder in ("nation", "competition", "club"):
        (ASSETS_DIR / folder).mkdir(parents=True, exist_ok=True)


def ensure_storage_files() -> None:
    _ensure_data_dir()
    ensure_tenant_storage()
    ensure_admin_storage()
    migrate_master_tenant_identity()
    if not USERS_PATH.exists():
        save_users([])
    if not SESSIONS_PATH.exists():
        save_stream_sessions([])
    if not SECURITY_LOGS_PATH.exists():
        save_security_logs([])
    if not INSTALL_LOGS_PATH.exists():
        save_install_logs([])
    if not SUBSCRIPTION_LOGS_PATH.exists():
        save_subscription_logs([])
    if not AUDIT_LOGS_PATH.exists():
        save_audit_logs([])
    if not EMAIL_LOGS_PATH.exists():
        save_email_logs([])
    if not RELEASE_INFO_PATH.exists():
        save_release_info(default_release_info())
    if not LICENSES_PATH.exists():
        save_licenses([])
    if not APK_VERSIONS_PATH.exists():
        save_apk_versions([])
    for admin in load_admins():
        ensure_admin_tenant_storage(str(admin.get("admin_id") or ""))
    migrate_legacy_admin_data()


def _default_branding() -> Dict[str, object]:
    return {
        "app_name": "Football Streaming",
        "package_name": "com.footballstreaming.default",
        "logo_url": "",
        "logo_file": "",
        "icon_url": "",
        "primary_color": "#11B37C",
        "secondary_color": "#7EE3AF",
        "accent_color": "#7EE3AF",
        "surface_color": "#0D1E2B",
        "background_color": "#07141E",
        "text_color": "#F2F8FF",
        "api_base_url": "",
        "server_url": "",
        "splash_screen": "",
        "default_language": "system",
        "supported_languages": ["en", "fr"],
    }


def _default_tenant_status() -> str:
    return "active"


def _normalize_admin_role(value: object, *, default: str = "client") -> str:
    role = str(value or "").strip().lower()
    if role in {"white_label", "platform_client", "client"}:
        return "client"
    if role in {"master", "master_admin"}:
        return "master"
    return default


def _normalize_admin_status(value: object, *, default: str = "active") -> str:
    status = str(value or "").strip().lower()
    if status in {"blocked", "inactive"}:
        return "blocked"
    if status == "active":
        return "active"
    return default


def _default_subscription_plans() -> List[Dict[str, object]]:
    return [
        {"id": "trial", "name": "3 Day Trial", "duration_days": TRIAL_DAYS, "price_label": "Free"},
        {"id": "6_months", "name": "6 Months", "duration_days": 183, "price_label": "Contact Admin"},
        {"id": "1_year", "name": "12 Months", "duration_days": 365, "price_label": "Contact Admin"},
    ]


def _base_tenant_payload(*, tenant_id: str = DEFAULT_TENANT_ID, name: str = "Football Streaming") -> Dict[str, object]:
    now = utc_now_iso()
    return {
        "tenant_id": tenant_id,
        "name": name,
        "email": "",
        "subscription_plan": "trial",
        "license_key": "",
        "server_ip": "",
        "status": _default_tenant_status(),
        "branding": _default_branding(),
        "subscription_plans": _default_subscription_plans(),
        "trial_policy": {"enabled": True, "duration_days": TRIAL_DAYS},
        "backend_url": "",
        "admin_credentials": {"username": "", "password": ""},
        "mobile_app_generated": False,
        "mobile_app_package_id": None,
        "mobile_app_created_at": None,
        "created_at": now,
        "updated_at": now,
    }


def _master_tenant_payload(name: str = "Master Platform") -> Dict[str, object]:
    payload = _base_tenant_payload(tenant_id=MASTER_TENANT_ID, name=name)
    payload["branding"] = {
        **payload["branding"],
        "app_name": name,
        "package_name": "com.footballstreaming.master",
    }
    return payload


def ensure_tenant_storage() -> None:
    if not TENANTS_PATH.exists():
        save_tenants([_base_tenant_payload()])


def ensure_admin_storage() -> None:
    if not ADMINS_PATH.exists():
        save_admins([])


def _normalize_tenant_id(tenant_id: Optional[str]) -> str:
    return _slugify(str(tenant_id or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID)


def _decorate_tenant(item: Dict[str, object]) -> Dict[str, object]:
    tenant = dict(item)
    tenant["tenant_id"] = _normalize_tenant_id(str(tenant.get("tenant_id") or DEFAULT_TENANT_ID))
    tenant["name"] = _normalize_name(str(tenant.get("name") or "Tenant")) or "Tenant"
    tenant["email"] = _normalize_email(str(tenant.get("email") or ""))
    tenant["subscription_plan"] = str(tenant.get("subscription_plan") or "trial").strip().lower() or "trial"
    tenant["license_key"] = str(tenant.get("license_key") or "").strip().upper()
    tenant["server_ip"] = str(tenant.get("server_ip") or "").strip()
    tenant["status"] = _normalize_admin_status(tenant.get("status"), default=_default_tenant_status())
    branding = tenant.get("branding") if isinstance(tenant.get("branding"), dict) else {}
    tenant["branding"] = {**_default_branding(), **branding}
    plans = tenant.get("subscription_plans")
    tenant["subscription_plans"] = plans if isinstance(plans, list) and plans else _default_subscription_plans()
    trial_policy = tenant.get("trial_policy") if isinstance(tenant.get("trial_policy"), dict) else {}
    tenant["trial_policy"] = {"enabled": True, "duration_days": TRIAL_DAYS, **trial_policy}
    admin_credentials = tenant.get("admin_credentials") if isinstance(tenant.get("admin_credentials"), dict) else {}
    tenant["admin_credentials"] = {
        "username": str(admin_credentials.get("username") or "").strip(),
        "password": str(admin_credentials.get("password") or ""),
    }
    tenant["backend_url"] = str(tenant.get("backend_url") or "").strip()
    tenant["mobile_app_generated"] = bool(tenant.get("mobile_app_generated") is True)
    package_id = str(tenant.get("mobile_app_package_id") or "").strip()
    tenant["mobile_app_package_id"] = package_id or None
    created_at = str(tenant.get("mobile_app_created_at") or "").strip()
    tenant["mobile_app_created_at"] = created_at or None
    tenant["updated_at"] = str(tenant.get("updated_at") or utc_now_iso())
    tenant["created_at"] = str(tenant.get("created_at") or tenant["updated_at"])
    return tenant


def load_tenants() -> List[Dict[str, object]]:
    payload = _read_json(TENANTS_PATH, [])
    items = payload if isinstance(payload, list) else []
    tenants = [_decorate_tenant(item) for item in items if isinstance(item, dict)]
    if not tenants:
        tenants = [_base_tenant_payload()]
        save_tenants(tenants)
    return tenants


def save_tenants(tenants: List[Dict[str, object]]) -> None:
    _write_json(TENANTS_PATH, [_decorate_tenant(item) for item in tenants])


def list_tenants() -> List[Dict[str, object]]:
    return sorted(load_tenants(), key=lambda item: str(item.get("name") or "").lower())


def get_tenant(tenant_id: Optional[str] = None) -> Dict[str, object]:
    normalized = _normalize_tenant_id(tenant_id)
    tenant = next((item for item in load_tenants() if item.get("tenant_id") == normalized), None)
    if tenant is not None:
        return tenant
    if normalized == MASTER_TENANT_ID:
        master_admin = next((item for item in load_admins() if _normalize_admin_role(item.get("role")) == "master"), None)
        master_tenant = _master_tenant_payload(str((master_admin or {}).get("name") or "Master Platform"))
        save_tenants([*load_tenants(), master_tenant])
        return _decorate_tenant(master_tenant)
    if normalized == DEFAULT_TENANT_ID:
        default_tenant = _base_tenant_payload()
        save_tenants([*load_tenants(), default_tenant])
        return _decorate_tenant(default_tenant)
    raise ValueError("Tenant not found.")


def upsert_tenant(
    *,
    tenant_id: Optional[str],
    name: str,
    email: str = "",
    subscription_plan: str = "",
    license_key: str = "",
    server_ip: str = "",
    status: str = "",
    branding: Optional[Dict[str, object]] = None,
    subscription_plans: Optional[List[Dict[str, object]]] = None,
    trial_policy: Optional[Dict[str, object]] = None,
    backend_url: str = "",
    admin_username: str = "",
    admin_password: str = "",
) -> Dict[str, object]:
    normalized_id = _normalize_tenant_id(tenant_id or _slugify(name))
    if not normalized_id:
        raise ValueError("tenant_id is required.")
    normalized_name = _normalize_name(name or "")
    if not normalized_name:
        raise ValueError("Tenant name is required.")
    existing = next((item for item in load_tenants() if item.get("tenant_id") == normalized_id), None)
    payload = _decorate_tenant(existing or _base_tenant_payload(tenant_id=normalized_id, name=normalized_name))
    payload["name"] = normalized_name
    if email or existing:
        payload["email"] = _normalize_email(email or payload.get("email") or "")
    if subscription_plan or existing:
        payload["subscription_plan"] = str(subscription_plan or payload.get("subscription_plan") or "trial").strip().lower() or "trial"
    if license_key or existing:
        payload["license_key"] = str(license_key or payload.get("license_key") or "").strip().upper()
    if server_ip or existing:
        payload["server_ip"] = str(server_ip or payload.get("server_ip") or "").strip()
    if status or existing:
        payload["status"] = _normalize_admin_status(status or payload.get("status"), default=_default_tenant_status())
    if branding:
        payload["branding"] = {**payload["branding"], **branding}
    if subscription_plans:
        payload["subscription_plans"] = subscription_plans
    if trial_policy:
        payload["trial_policy"] = {**payload["trial_policy"], **trial_policy}
    payload["backend_url"] = str(backend_url or payload.get("backend_url") or "").strip()
    if admin_username or admin_password or not existing:
        payload["admin_credentials"] = {
            "username": str(admin_username or payload["admin_credentials"].get("username") or "").strip(),
            "password": str(admin_password or payload["admin_credentials"].get("password") or ""),
        }
    payload["updated_at"] = utc_now_iso()
    tenants = [item for item in load_tenants() if item.get("tenant_id") != normalized_id]
    tenants.append(payload)
    save_tenants(tenants)
    admin = get_admin_by_tenant_id(payload["tenant_id"])
    if admin is not None:
        ensure_admin_tenant_storage(str(admin.get("admin_id") or ""))
        _write_json(_tenant_file_path(str(admin.get("admin_id") or ""), "branding.json"), payload["branding"])
    return payload


def update_tenant_branding(tenant_id: str, branding: Dict[str, object]) -> Dict[str, object]:
    tenant = get_tenant(tenant_id)
    return upsert_tenant(
        tenant_id=tenant["tenant_id"],
        name=str(tenant["name"]),
        email=str(tenant.get("email") or ""),
        subscription_plan=str(tenant.get("subscription_plan") or "trial"),
        license_key=str(tenant.get("license_key") or ""),
        server_ip=str(tenant.get("server_ip") or ""),
        status=str(tenant.get("status") or _default_tenant_status()),
        branding={**tenant["branding"], **branding},
        subscription_plans=list(tenant["subscription_plans"]),
        trial_policy=dict(tenant["trial_policy"]),
        backend_url=str(tenant.get("backend_url") or ""),
        admin_username=str(tenant["admin_credentials"].get("username") or ""),
        admin_password=str(tenant["admin_credentials"].get("password") or ""),
    )


def update_tenant_mobile_app_status(
    tenant_id: str,
    *,
    mobile_app_generated: Optional[bool] = None,
    mobile_app_package_id: Optional[str] = None,
    mobile_app_created_at: Optional[str] = None,
) -> Dict[str, object]:
    tenant = get_tenant(tenant_id)
    updated = dict(tenant)
    if mobile_app_generated is not None:
        updated["mobile_app_generated"] = bool(mobile_app_generated)
    if mobile_app_package_id is not None:
        normalized_package_id = str(mobile_app_package_id or "").strip()
        updated["mobile_app_package_id"] = normalized_package_id or None
    if mobile_app_created_at is not None:
        normalized_created_at = str(mobile_app_created_at or "").strip()
        updated["mobile_app_created_at"] = normalized_created_at or None
    updated["updated_at"] = utc_now_iso()
    tenants = [item for item in load_tenants() if item.get("tenant_id") != updated["tenant_id"]]
    tenants.append(updated)
    save_tenants(tenants)
    return _decorate_tenant(updated)


def update_tenant_record(tenant_id: str, patch: Dict[str, object]) -> Dict[str, object]:
    tenant = get_tenant(tenant_id)
    updated = {
        **tenant,
        **(patch or {}),
        "tenant_id": tenant["tenant_id"],
        "updated_at": utc_now_iso(),
    }
    tenants = [item for item in load_tenants() if item.get("tenant_id") != tenant["tenant_id"]]
    tenants.append(updated)
    save_tenants(tenants)
    return _decorate_tenant(updated)


def _supported_languages_from_branding(branding: Dict[str, object]) -> List[str]:
    raw = branding.get("supported_languages")
    if isinstance(raw, list):
        values = [str(item or "").strip().lower() for item in raw]
        items = [item for item in values if item]
    else:
        items = []
    if not items:
        items = ["en", "fr"]
    normalized: List[str] = []
    for item in items:
        if item not in normalized:
            normalized.append(item)
    return normalized


def _default_language_from_branding(branding: Dict[str, object]) -> str:
    value = str(branding.get("default_language") or "system").strip().lower() or "system"
    if value == "system":
        return value
    return value if value in _supported_languages_from_branding(branding) else "system"


def get_runtime_feature_flags(tenant_id: Optional[str] = None) -> Dict[str, bool]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    admin = get_admin_by_tenant_id(normalized_tenant_id) or {}
    is_master = _normalize_admin_role(admin.get("role"), default="client") == "master" or normalized_tenant_id == MASTER_TENANT_ID
    return {
        "streams": True,
        "football_catalog": True,
        "approval_panel": True,
        "provider_groups": True,
        "mobile_app_generation": True,
        "branding_updates": True,
        "language_switching": True,
        "desktop_auto_updates": True,
        "mobile_dynamic_updates": True,
        "live_scores": is_master,
        "standings": is_master,
        "schedules": is_master,
        "core_feature_updates": is_master,
        "tenant_locked": not is_master,
    }


def get_mobile_runtime_manifest(tenant_id: Optional[str] = None, *, current_version: str = "") -> Dict[str, object]:
    tenant = get_branding_config(tenant_id)
    branding = tenant.get("branding") if isinstance(tenant.get("branding"), dict) else {}
    feature_flags = get_runtime_feature_flags(str(tenant.get("tenant_id") or tenant_id or DEFAULT_TENANT_ID))
    latest_apk = get_latest_apk_version() or {}
    minimum_supported_version = str(latest_apk.get("version") or "0.1.0")
    current = str(current_version or "").strip() or "0.0.0"
    content_revision = str(tenant.get("mobile_app_created_at") or tenant.get("mobile_content_revision") or tenant.get("backend_url") or tenant.get("tenant_id") or "")
    return {
        "latest_version": str(latest_apk.get("version") or current or "0.1.0"),
        "minimum_supported_version": minimum_supported_version,
        "current_version": current,
        "is_supported": update_semver_key(current) >= update_semver_key(minimum_supported_version),
        "requires_store_update": bool(latest_apk),
        "tenant_locked": bool(feature_flags.get("tenant_locked")),
        "update_url": str(latest_apk.get("file_path") or ""),
        "force_update": bool(latest_apk.get("force_update")),
        "language": {
            "default": _default_language_from_branding(branding),
            "supported": _supported_languages_from_branding(branding),
        },
        "feature_flags": feature_flags,
        "content_revision": str(content_revision or tenant.get("backend_url") or ""),
        "branding_revision": str(tenant.get("mobile_app_created_at") or tenant.get("backend_url") or ""),
    }


def get_api_version_payload(
    tenant_id: Optional[str] = None,
    *,
    current_version: str = "",
    platform: str = "",
    client: str = "",
) -> Dict[str, object]:
    tenant = get_branding_config(tenant_id)
    desktop_release = check_for_desktop_update(current_version or "0.0.0", platform=platform or "")
    mobile_release = get_mobile_runtime_manifest(str(tenant.get("tenant_id") or tenant_id or DEFAULT_TENANT_ID), current_version=current_version)
    return {
        "generated_at": utc_now_iso(),
        "client": str(client or "all").strip().lower() or "all",
        "tenant_id": tenant.get("tenant_id"),
        "tenant_locked": bool(mobile_release.get("tenant_locked")),
        "language": mobile_release.get("language"),
        "feature_flags": mobile_release.get("feature_flags"),
        "desktop": desktop_release,
        "mobile": mobile_release,
    }


def authenticate_tenant_admin(tenant_id: str, username: str, password: str) -> Dict[str, object]:
    tenant = get_tenant(tenant_id)
    logger.info(
        "Tenant admin login lookup tenant_id=%s requested_username=%s resolved_tenant_id=%s",
        tenant_id,
        str(username or "").strip(),
        str(tenant.get("tenant_id") or ""),
    )
    credentials = tenant.get("admin_credentials") or {}
    configured_username = str(credentials.get("username") or "").strip()
    configured_password = str(credentials.get("password") or "")
    requested_username = str(username or "").strip()
    requested_password = str(password or "")

    if configured_username and configured_password:
        if not (
            secrets.compare_digest(configured_username, requested_username)
            and secrets.compare_digest(configured_password, requested_password)
        ):
            raise ValueError("Invalid tenant admin credentials.")
        return tenant

    admin = get_admin_by_tenant_id(str(tenant.get("tenant_id") or ""))
    if admin is not None:
        expected = _hash_secret(requested_password, str(admin.get("password_salt") or ""))
        if secrets.compare_digest(str(admin.get("email") or "").strip().lower(), _normalize_email(requested_username)) and secrets.compare_digest(expected, str(admin.get("password_hash") or "")):
            logger.info(
                "Tenant admin login used linked admin credentials tenant_id=%s admin_id=%s",
                str(tenant.get("tenant_id") or ""),
                str(admin.get("admin_id") or ""),
            )
            return tenant

    raise ValueError("Tenant admin credentials are not configured.")


def get_branding_config(tenant_id: Optional[str] = None) -> Dict[str, object]:
    tenant = get_tenant(tenant_id)
    admin = get_admin_by_tenant_id(tenant.get("tenant_id"))
    meta = load_tenant_meta(admin_id=str(admin.get("admin_id") or ""), tenant_id=tenant.get("tenant_id")) if admin else {}
    branding_path = _tenant_file_path(str(admin.get("admin_id") or ""), "branding.json") if admin else None
    branding_snapshot = _read_json(branding_path, tenant["branding"]) if branding_path else tenant["branding"]
    branding = {**tenant["branding"], **(branding_snapshot if isinstance(branding_snapshot, dict) else {})}
    api_base_url = get_api_base_url()
    configured_backend_url = str(
        tenant.get("backend_url")
        or branding.get("server_url")
        or branding.get("api_base_url")
        or ""
    ).strip()
    resolved_backend_url = str(
        configured_backend_url
        or api_base_url
    ).strip() or api_base_url
    backend_url_source = "configured" if configured_backend_url else "default_local"
    backend_url_notice = (
        ""
        if configured_backend_url
        else f"Using local development backend ({api_base_url})."
    )
    branding["api_base_url"] = str(branding.get("api_base_url") or api_base_url)
    branding["server_url"] = str(branding.get("server_url") or resolved_backend_url)
    feature_flags = get_runtime_feature_flags(str(tenant.get("tenant_id") or tenant_id or DEFAULT_TENANT_ID))
    language = {
        "default": _default_language_from_branding(branding),
        "supported": _supported_languages_from_branding(branding),
    }
    return {
        "tenant_id": tenant["tenant_id"],
        "name": tenant["name"],
        "email": tenant.get("email") or "",
        "subscription_plan": tenant.get("subscription_plan") or "trial",
        "license_key": tenant.get("license_key") or "",
        "server_ip": tenant.get("server_ip") or "",
        "status": tenant.get("status") or _default_tenant_status(),
        "branding": branding,
        "mobile_app_generated": bool(tenant.get("mobile_app_generated") is True),
        "mobile_app_package_id": tenant.get("mobile_app_package_id"),
        "mobile_app_created_at": tenant.get("mobile_app_created_at"),
        "subscription_plans": tenant["subscription_plans"],
        "trial_policy": tenant["trial_policy"],
        "backend_url": resolved_backend_url,
        "backend_url_source": backend_url_source,
        "backend_url_notice": backend_url_notice,
        "language": language,
        "feature_flags": feature_flags,
        "mobile_auth": {
            "api_token": str(meta.get("mobile_api_token") or ""),
            "server_id": str(meta.get("server_id") or ""),
        },
    }


def _default_admin_plans() -> List[Dict[str, object]]:
    return [
        {"id": "trial", "name": "Trial", "duration_days": TRIAL_DAYS, "price_label": "Free"},
        {"id": "6_months", "name": "6 Months", "duration_days": 183, "price_label": "Placeholder"},
        {"id": "1_year", "name": "12 Months", "duration_days": 365, "price_label": "Placeholder"},
    ]


def _tenant_default_metadata() -> Dict[str, List[Dict[str, object]]]:
    return {"nations": [], "competitions": [], "clubs": [], "competition_club_links": []}


def _tenant_default_provider_payload() -> List[Dict[str, object]]:
    return []


def _normalize_provider_record(item: Dict[str, object], tenant_id: Optional[str] = None) -> Dict[str, object]:
    provider = dict(item)
    normalized_tenant_id = _normalize_tenant_id(provider.get("tenant_id") or tenant_id)
    provider_id = str(provider.get("id") or provider.get("provider_id") or "active").strip() or "active"
    iptv_url = str(
        provider.get("iptv_url")
        or provider.get("m3u_playlist_url")
        or provider.get("xtream_server_url")
        or ""
    ).strip()
    provider["id"] = provider_id
    provider["provider_id"] = provider_id
    provider["tenant_id"] = normalized_tenant_id
    provider["name"] = _normalize_name(str(provider.get("name") or "Active Provider")) or "Active Provider"
    provider["iptv_url"] = iptv_url
    provider["status"] = "active" if str(provider.get("status") or ("active" if provider.get("active") is not False else "inactive")).strip().lower() == "active" else "inactive"
    provider["active"] = provider["status"] == "active"
    provider["saved_at"] = str(provider.get("saved_at") or utc_now_iso())
    return provider


def _normalize_provider_group_record(item: Dict[str, object], tenant_id: Optional[str] = None) -> Dict[str, object]:
    group = dict(item)
    group_id = str(group.get("id") or group.get("group_id") or "").strip()
    provider_id = str(group.get("provider_id") or "").strip() or "active"
    name = str(group.get("group_name") or group.get("name") or "").strip() or "Ungrouped"
    normalized_tenant_id = _normalize_tenant_id(group.get("tenant_id") or tenant_id)
    return {
        "id": group_id or _slugify(f"{provider_id}-{name}"),
        "group_id": group_id or _slugify(f"{provider_id}-{name}"),
        "tenant_id": normalized_tenant_id,
        "provider_id": provider_id,
        "group_name": name,
        "name": name,
        "channel_count": int(group.get("channel_count") or 0),
    }


def _normalize_channel_record(item: Dict[str, object], tenant_id: Optional[str] = None) -> Dict[str, object]:
    channel = dict(item)
    normalized_tenant_id = _normalize_tenant_id(channel.get("tenant_id") or tenant_id)
    provider_id = str(channel.get("provider_id") or "active").strip() or "active"
    group_id = str(channel.get("group_id") or "").strip()
    channel_id = str(channel.get("id") or channel.get("channel_id") or channel.get("stream_id") or "").strip()
    channel_name = str(channel.get("channel_name") or channel.get("name") or channel.get("raw_name") or "Unnamed channel").strip() or "Unnamed channel"
    stream_url = str(channel.get("stream_url") or channel.get("url") or "").strip()
    return {
        **channel,
        "id": channel_id,
        "channel_id": channel_id,
        "tenant_id": normalized_tenant_id,
        "provider_id": provider_id,
        "group_id": group_id,
        "channel_name": channel_name,
        "name": channel_name,
        "stream_url": stream_url,
    }


def _normalize_mobile_app_record(item: Dict[str, object], tenant_id: Optional[str] = None) -> Dict[str, object]:
    app_record = dict(item)
    normalized_tenant_id = _normalize_tenant_id(app_record.get("tenant_id") or tenant_id)
    return {
        "id": str(app_record.get("id") or uuid4().hex),
        "tenant_id": normalized_tenant_id,
        "package_id": str(app_record.get("package_id") or app_record.get("mobile_app_package") or "").strip().lower(),
        "app_name": str(app_record.get("app_name") or "").strip(),
        "logo_url": str(app_record.get("logo_url") or "").strip(),
        "theme_color": str(app_record.get("theme_color") or app_record.get("primary_color") or "").strip(),
        "generated_at": str(app_record.get("generated_at") or utc_now_iso()),
        "artifact_name": str(app_record.get("artifact_name") or "").strip(),
        "build_id": str(app_record.get("build_id") or "").strip(),
    }


def get_tenant_data_path(admin_id: str) -> Path:
    normalized = str(admin_id or "").strip()
    if not normalized:
        raise ValueError("admin_id is required.")
    path = TENANT_DATA_DIR / normalized
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tenant_file_path(admin_id: str, filename: str) -> Path:
    return get_admin_storage_path(admin_id) / filename


def _tenant_table_path(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None, table_name: str) -> Path:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    if not resolved_admin_id:
        raise ValueError("Tenant storage is required.")
    return _tenant_file_path(resolved_admin_id, table_name)


def _load_tenant_table(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None, table_name: str) -> List[Dict[str, object]]:
    payload = _read_json(_tenant_table_path(admin_id=admin_id, tenant_id=tenant_id, table_name=table_name), [])
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _save_tenant_table(items: List[Dict[str, object]], *, admin_id: Optional[str] = None, tenant_id: Optional[str] = None, table_name: str) -> None:
    _write_json(_tenant_table_path(admin_id=admin_id, tenant_id=tenant_id, table_name=table_name), items)


def load_tenant_meta(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, object]:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    if not resolved_admin_id:
        return {"setup_completed": True, "mobile_api_token": "", "admin_id": "", "server_id": "", "device_id": ""}
    ensure_admin_tenant_storage(resolved_admin_id)
    path = _tenant_file_path(resolved_admin_id, "meta.json")
    payload = _read_json(path, {})
    meta = payload if isinstance(payload, dict) else {}
    admin = get_admin_by_id(resolved_admin_id) or {}
    meta["setup_completed"] = bool(meta.get("setup_completed", False))
    meta["mobile_api_token"] = str(meta.get("mobile_api_token") or secrets.token_urlsafe(24))
    meta["admin_id"] = resolved_admin_id
    meta["tenant_id"] = _normalize_tenant_id(tenant_id or admin.get("tenant_id"))
    meta["server_id"] = str(admin.get("server_id") or meta.get("server_id") or "").strip()
    meta["device_id"] = str(admin.get("device_id") or meta.get("device_id") or "").strip()
    _write_json(path, meta)
    return meta


def save_tenant_meta(meta: Dict[str, object], *, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, object]:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    if not resolved_admin_id:
        raise ValueError("Admin not found.")
    current = load_tenant_meta(admin_id=resolved_admin_id, tenant_id=tenant_id)
    next_meta = {**current, **(meta or {})}
    next_meta["setup_completed"] = bool(next_meta.get("setup_completed", False))
    _write_json(_tenant_file_path(resolved_admin_id, "meta.json"), next_meta)
    return next_meta


def get_setup_status(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, object]:
    meta = load_tenant_meta(admin_id=admin_id, tenant_id=tenant_id)
    return {
        "setup_completed": bool(meta.get("setup_completed")),
        "steps": [
            {"id": "register_server", "label": "Register server", "completed": bool(meta.get("server_id"))},
            {"id": "add_provider", "label": "Add IPTV provider", "completed": bool(load_provider_settings(admin_id=admin_id, tenant_id=tenant_id))},
            {"id": "add_league", "label": "Add league", "completed": len(list_nations(tenant_id=tenant_id)) > 0},
            {"id": "publish_mobile", "label": "Publish mobile app", "completed": bool(meta.get("setup_completed"))},
        ],
        "mobile_api_token": str(meta.get("mobile_api_token") or ""),
        "server_id": str(meta.get("server_id") or ""),
    }


def mark_setup_completed(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, object]:
    meta = save_tenant_meta({"setup_completed": True}, admin_id=admin_id, tenant_id=tenant_id)
    return {
        "setup_completed": True,
        "mobile_api_token": str(meta.get("mobile_api_token") or ""),
        "server_id": str(meta.get("server_id") or ""),
    }


def validate_mobile_tenant_access(
    *,
    api_token: str,
    tenant_id: str,
    device_id: str,
    server_id: str,
) -> Dict[str, object]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    admin = get_admin_by_tenant_id(normalized_tenant_id)
    if admin is None:
        raise ValueError("Tenant not found.")
    meta = load_tenant_meta(admin_id=str(admin.get("admin_id") or ""), tenant_id=normalized_tenant_id)
    if not secrets.compare_digest(str(meta.get("mobile_api_token") or ""), str(api_token or "").strip()):
        raise ValueError("Invalid tenant api_token.")
    expected_device = str(meta.get("device_id") or "").strip()
    expected_server = str(meta.get("server_id") or "").strip()
    if expected_device and str(device_id or "").strip() != expected_device:
        raise ValueError("Device binding mismatch.")
    if expected_server and str(server_id or "").strip() != expected_server:
        raise ValueError("Server binding mismatch.")
    return {
        "admin_id": str(admin.get("admin_id") or ""),
        "tenant_id": normalized_tenant_id,
        "device_id": expected_device,
        "server_id": expected_server,
    }


def _normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _version_key(value: str) -> tuple:
    return update_semver_key(value)


def _hash_secret(secret: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        str(secret or "").encode("utf-8"),
        str(salt or "").encode("utf-8"),
        120_000,
    ).hex()


def _admin_subscription_delta(plan_id: str) -> timedelta:
    normalized = str(plan_id or "trial").strip().lower()
    days = next(
        (int(item.get("duration_days") or 0) for item in _default_admin_plans() if str(item.get("id") or "").strip().lower() == normalized),
        0,
    )
    if days > 0:
        return timedelta(days=days)
    return _SUBSCRIPTION_PLAN_DELTAS.get(normalized, timedelta(days=TRIAL_DAYS))


def _apply_master_admin_defaults(admin: Dict[str, object]) -> Dict[str, object]:
    admin["plan_id"] = "unlimited"
    admin["trial_days"] = 0
    admin["subscription_status"] = "active"
    admin["status"] = "active"
    admin["subscription_end"] = ""
    admin["subscription_end_date"] = ""
    return admin


def _decorate_admin(item: Dict[str, object]) -> Dict[str, object]:
    now = utc_now()
    admin = dict(item)
    admin["admin_id"] = str(admin.get("admin_id") or uuid4().hex)
    admin["tenant_id"] = _normalize_tenant_id(admin.get("tenant_id"))
    admin["name"] = _normalize_name(str(admin.get("name") or "")) or "Admin"
    admin["email"] = _normalize_email(str(admin.get("email") or ""))
    admin["plan_id"] = str(admin.get("plan_id") or "trial").strip().lower() or "trial"
    admin["password_salt"] = str(admin.get("password_salt") or "")
    admin["password_hash"] = str(admin.get("password_hash") or "")
    admin["api_token_hash"] = str(admin.get("api_token_hash") or "")
    admin["subscription_started_at"] = str(admin.get("subscription_started_at") or admin.get("subscription_start") or utc_now_iso())
    admin["subscription_end"] = str(admin.get("subscription_end") or admin.get("subscription_end_date") or "")
    admin["subscription_status"] = str(admin.get("subscription_status") or "active").strip().lower() or "active"
    admin["subscription_start_date"] = str(admin.get("subscription_start_date") or admin.get("subscription_start") or admin["subscription_started_at"])
    admin["subscription_end_date"] = str(admin.get("subscription_end_date") or admin["subscription_end"])
    admin["subscription_start"] = admin["subscription_start_date"]
    admin["subscription_end"] = admin["subscription_end_date"] or admin["subscription_end"]
    admin["device_id"] = str(admin.get("device_id") or "").strip()
    admin["device_transfer_available_at"] = str(admin.get("device_transfer_available_at") or "")
    admin["server_id"] = str(admin.get("server_id") or "").strip()
    admin["server_domain"] = str(admin.get("server_domain") or "").strip()
    admin["server_ip"] = str(admin.get("server_ip") or "").strip()
    admin["hardware_hash"] = str(admin.get("hardware_hash") or "").strip()
    admin["server_registered_at"] = str(admin.get("server_registered_at") or "")
    admin["server_reset_available_at"] = str(admin.get("server_reset_available_at") or "")
    admin["branding_info"] = dict(admin.get("branding_info") or {})
    admin["status"] = _normalize_admin_status(admin.get("status"), default="active")
    admin["role"] = _normalize_admin_role(admin.get("role"), default="client")
    admin["trial_days"] = int(admin.get("trial_days") or (TRIAL_DAYS if admin["plan_id"] == "trial" else 0) or 0)
    admin["payment_provider"] = str(admin.get("payment_provider") or "").strip().lower()
    admin["payment_reference"] = str(admin.get("payment_reference") or "").strip()
    admin["last_payment_at"] = str(admin.get("last_payment_at") or "")
    admin["created_at"] = str(admin.get("created_at") or utc_now_iso())
    admin["updated_at"] = str(admin.get("updated_at") or admin["created_at"])

    is_master = admin["role"] == "master"
    subscription_end = parse_datetime(admin["subscription_end"])
    if is_master:
        admin = _apply_master_admin_defaults(admin)
    elif subscription_end and subscription_end < now:
        admin["subscription_status"] = "expired"
        admin["status"] = "blocked" if admin["status"] == "blocked" else "active"
    elif admin["subscription_status"] not in {"active", "trial", "expired"}:
        admin["subscription_status"] = "active"
    elif admin["status"] not in {"active", "blocked"}:
        admin["status"] = "active"
    return admin


def load_admins() -> List[Dict[str, object]]:
    payload = _read_json(ADMINS_PATH, [])
    items = payload if isinstance(payload, list) else []
    admins = [_decorate_admin(item) for item in items if isinstance(item, dict)]
    changed = False
    if admins:
        master_exists = any(_normalize_admin_role(admin.get("role")) == "master" for admin in admins)
        if not master_exists:
            admins[0]["role"] = "master"
            changed = True
        for index, admin in enumerate(admins):
            role = _normalize_admin_role(admin.get("role"), default="")
            if role not in {"master", "client"}:
                admin["role"] = "master" if index == 0 and not master_exists else "client"
                changed = True
            elif role != admin.get("role"):
                admin["role"] = role
                changed = True
    if changed:
        save_admins(admins)
    return admins


def save_admins(admins: List[Dict[str, object]]) -> None:
    _write_json(ADMINS_PATH, [_decorate_admin(item) for item in admins])


def _replace_admin(payload: Dict[str, object]) -> Dict[str, object]:
    admins = [item for item in load_admins() if str(item.get("admin_id") or "") != str(payload.get("admin_id") or "")]
    payload["updated_at"] = utc_now_iso()
    admins.append(_decorate_admin(payload))
    save_admins(admins)
    return _decorate_admin(payload)


def list_admins() -> List[Dict[str, object]]:
    return sorted(load_admins(), key=lambda item: item.get("email", ""))


def list_admin_summaries() -> List[Dict[str, object]]:
    return [admin_session_payload(item) for item in list_admins()]


def list_platform_clients() -> List[Dict[str, object]]:
    return [admin_session_payload(item) for item in list_admins() if _normalize_admin_role(item.get("role")) != "master"]


def get_platform_client_stats() -> Dict[str, int]:
    admins = [item for item in list_admins() if _normalize_admin_role(item.get("role")) != "master"]
    total = len(admins)
    active = sum(1 for item in admins if str(item.get("status") or "") == "active")
    blocked = sum(1 for item in admins if str(item.get("status") or "") == "blocked")
    trial = sum(1 for item in admins if str(item.get("subscription_status") or "") == "trial")
    expired = sum(1 for item in admins if str(item.get("subscription_status") or "") == "expired")
    return {
        "total_clients": total,
        "active_clients": active,
        "trial_clients": trial,
        "blocked_clients": blocked,
        "expired_clients": expired,
    }


def default_release_info() -> Dict[str, object]:
    metadata = default_update_metadata()
    return {
        "latest_version": str(metadata.get("version") or "0.1.0"),
        "minimum_supported_version": str(metadata.get("minimum_supported_version") or "0.0.0"),
        "download_url": str(metadata.get("download_url") or ""),
        "release_notes": str(metadata.get("release_notes") or ""),
        "mandatory": bool(metadata.get("mandatory")),
        "published_at": str(metadata.get("published_at") or utc_now_iso()),
        "release_date": str(metadata.get("release_date") or ""),
    }


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    match = _DATA_URL_RE.match(str(data_url or "").strip())
    if not match:
        raise ValueError("Upload must use a base64 data URL.")
    try:
        return base64.b64decode(match.group("data")), str(match.group("mime") or "application/octet-stream")
    except Exception as exc:
        raise ValueError("Invalid base64 upload payload.") from exc


def _normalize_apk_version(item: Dict[str, object]) -> Dict[str, object]:
    uploaded_at = str(item.get("uploaded_at") or utc_now_iso())
    version = str(item.get("version") or "").strip()
    file_path = str(item.get("file_path") or "").strip()
    return {
        "id": str(item.get("id") or uuid4().hex),
        "version": version,
        "file_path": file_path,
        "uploaded_at": uploaded_at,
        "is_latest": bool(item.get("is_latest")),
        "force_update": bool(item.get("force_update")),
    }


def load_apk_versions() -> List[Dict[str, object]]:
    payload = _read_json(APK_VERSIONS_PATH, [])
    items = [_normalize_apk_version(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    if not any(item.get("is_latest") for item in items) and items:
        latest_id = max(items, key=lambda item: _version_key(str(item.get("version") or "0.0.0"))).get("id")
        items = [{**item, "is_latest": item.get("id") == latest_id} for item in items]
        save_apk_versions(items)
        return items
    return sorted(items, key=lambda item: (_version_key(str(item.get("version") or "0.0.0")), str(item.get("uploaded_at") or "")), reverse=True)


def save_apk_versions(items: List[Dict[str, object]]) -> None:
    normalized = [_normalize_apk_version(item) for item in items]
    latest_seen = False
    for item in normalized:
        if item["is_latest"] and not latest_seen:
            latest_seen = True
        else:
            item["is_latest"] = False
    _write_json(APK_VERSIONS_PATH, normalized)


def list_apk_versions() -> List[Dict[str, object]]:
    return load_apk_versions()


def get_latest_apk_version() -> Optional[Dict[str, object]]:
    items = load_apk_versions()
    return next((item for item in items if item.get("is_latest")), items[0] if items else None)


def upload_apk_version(*, version: str, filename: str, file_data: str) -> Dict[str, object]:
    normalized_version = str(version or "").strip()
    if not normalized_version:
        raise ValueError("APK version is required.")
    safe_name = Path(str(filename or "").strip()).name
    if not safe_name.lower().endswith(".apk"):
        raise ValueError("APK filename must end with .apk")
    content, _ = _decode_data_url(file_data)
    if not content:
        raise ValueError("APK file is empty.")
    relative_path = f"/downloads/app-v{normalized_version}.apk"
    absolute_path = APP_DOWNLOADS_DIR / f"app-v{normalized_version}.apk"
    absolute_path.write_bytes(content)
    items = load_apk_versions()
    previous = next((item for item in items if str(item.get("version") or "") == normalized_version), None)
    entry = _normalize_apk_version(
        {
            "id": uuid4().hex,
            "version": normalized_version,
            "file_path": relative_path,
            "uploaded_at": utc_now_iso(),
            "is_latest": bool(previous.get("is_latest")) if previous else not items,
            "force_update": bool(previous.get("force_update")) if previous else False,
        }
    )
    items = [item for item in items if str(item.get("version") or "") != normalized_version]
    items.append(entry)
    if len(items) == 1:
        items[0]["is_latest"] = True
    save_apk_versions(sorted(items, key=lambda item: (_version_key(str(item.get("version") or "0.0.0")), str(item.get("uploaded_at") or "")), reverse=True))
    return entry


def set_latest_apk_version(apk_id: str, *, force_update: bool = False) -> Dict[str, object]:
    target_id = str(apk_id or "").strip()
    if not target_id:
        raise ValueError("APK id is required.")
    items = load_apk_versions()
    if not items:
        raise ValueError("No APK versions uploaded yet.")
    found = None
    for item in items:
        item["is_latest"] = item.get("id") == target_id
        if item["is_latest"]:
            item["force_update"] = bool(force_update)
            found = item
        else:
            item["force_update"] = False
    if found is None:
        raise ValueError("APK version not found.")
    save_apk_versions(items)
    return _normalize_apk_version(found)


def _normalize_install_log(item: Dict[str, object]) -> Dict[str, object]:
    admin = get_admin_by_id(str(item.get("admin_id") or "")) or {}
    install_timestamp = str(item.get("install_timestamp") or item.get("timestamp") or utc_now_iso())
    normalized = {
        "id": str(item.get("id") or uuid4().hex),
        "admin_id": str(item.get("admin_id") or admin.get("admin_id") or ""),
        "tenant_id": str(item.get("tenant_id") or admin.get("tenant_id") or ""),
        "device_id": str(item.get("device_id") or "").strip(),
        "app_version": str(item.get("app_version") or "").strip(),
        "subscription_status": str(item.get("subscription_status") or admin.get("subscription_status") or "unknown"),
        "install_timestamp": install_timestamp,
        "timestamp": install_timestamp,
        "admin_name": str(item.get("admin_name") or admin.get("name") or ""),
        "admin_email": str(item.get("admin_email") or admin.get("email") or ""),
        "platform": str(item.get("platform") or "desktop"),
    }
    return normalized


def _normalize_subscription_log(item: Dict[str, object]) -> Dict[str, object]:
    admin = get_admin_by_id(str(item.get("admin_id") or "")) or {}
    plan = str(item.get("subscription_plan") or item.get("plan_id") or admin.get("plan_id") or "").strip().lower()
    normalized = {
        "id": str(item.get("id") or uuid4().hex),
        "admin_id": str(item.get("admin_id") or admin.get("admin_id") or ""),
        "tenant_id": str(item.get("tenant_id") or admin.get("tenant_id") or ""),
        "subscription_plan": plan,
        "start_date": str(item.get("start_date") or admin.get("subscription_start_date") or ""),
        "end_date": str(item.get("end_date") or admin.get("subscription_end_date") or ""),
        "timestamp": str(item.get("timestamp") or utc_now_iso()),
        "subscription_status": str(item.get("subscription_status") or admin.get("subscription_status") or "unknown"),
        "admin_name": str(item.get("admin_name") or admin.get("name") or ""),
        "admin_email": str(item.get("admin_email") or admin.get("email") or ""),
        "estimated_revenue": float(item.get("estimated_revenue") or _SUBSCRIPTION_PLAN_REVENUE.get(plan, 0.0)),
    }
    return normalized


def _normalize_audit_log(item: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": str(item.get("id") or uuid4().hex),
        "timestamp": str(item.get("timestamp") or utc_now_iso()),
        "path": str(item.get("path") or ""),
        "method": str(item.get("method") or "GET"),
        "status_code": int(item.get("status_code") or 0),
        "admin_id": str(item.get("admin_id") or ""),
        "tenant_id": str(item.get("tenant_id") or ""),
        "device_id": str(item.get("device_id") or ""),
        "server_id": str(item.get("server_id") or ""),
        "scope": str(item.get("scope") or ""),
        "duration_ms": int(item.get("duration_ms") or 0),
    }


def _normalize_email_log(item: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": str(item.get("id") or uuid4().hex),
        "type": str(item.get("type") or "subscription_reminder"),
        "timestamp": str(item.get("timestamp") or utc_now_iso()),
        "admin_id": str(item.get("admin_id") or ""),
        "tenant_id": str(item.get("tenant_id") or ""),
        "email": str(item.get("email") or ""),
        "subject": str(item.get("subject") or ""),
        "status": str(item.get("status") or "logged"),
        "detail": str(item.get("detail") or ""),
    }


def load_install_logs() -> List[Dict[str, object]]:
    payload = _read_json(INSTALL_LOGS_PATH, [])
    items = [_normalize_install_log(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    if items != payload:
        save_install_logs(items)
    return items


def save_install_logs(logs: List[Dict[str, object]]) -> None:
    _write_json(INSTALL_LOGS_PATH, [_normalize_install_log(item) for item in logs][-5000:])


def load_subscription_logs() -> List[Dict[str, object]]:
    payload = _read_json(SUBSCRIPTION_LOGS_PATH, [])
    items = [_normalize_subscription_log(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    if items != payload:
        save_subscription_logs(items)
    return items


def save_subscription_logs(logs: List[Dict[str, object]]) -> None:
    _write_json(SUBSCRIPTION_LOGS_PATH, [_normalize_subscription_log(item) for item in logs][-5000:])


def _load_persisted_audit_logs() -> List[Dict[str, object]]:
    payload = _read_json(AUDIT_LOGS_PATH, [])
    items = [_normalize_audit_log(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    if items != payload:
        _write_json(AUDIT_LOGS_PATH, items[-MAX_AUDIT_LOGS:])
    return items


def load_audit_logs() -> List[Dict[str, object]]:
    return _load_persisted_audit_logs() + list(_AUDIT_LOG_BUFFER)


def save_audit_logs(logs: List[Dict[str, object]]) -> None:
    global _AUDIT_LOG_BUFFER
    _AUDIT_LOG_BUFFER = []
    _write_json(AUDIT_LOGS_PATH, [_normalize_audit_log(item) for item in logs][-MAX_AUDIT_LOGS:])


def flush_audit_logs(force: bool = False) -> None:
    global _AUDIT_LOG_BUFFER
    if not _AUDIT_LOG_BUFFER:
        return
    if not force and len(_AUDIT_LOG_BUFFER) < _AUDIT_LOG_BUFFER_LIMIT:
        return
    logs = _load_persisted_audit_logs()
    logs.extend(_AUDIT_LOG_BUFFER)
    _AUDIT_LOG_BUFFER = []
    _write_json(AUDIT_LOGS_PATH, [_normalize_audit_log(item) for item in logs][-MAX_AUDIT_LOGS:])


def load_email_logs() -> List[Dict[str, object]]:
    payload = _read_json(EMAIL_LOGS_PATH, [])
    items = [_normalize_email_log(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    if items != payload:
        save_email_logs(items)
    return items


def save_email_logs(logs: List[Dict[str, object]]) -> None:
    _write_json(EMAIL_LOGS_PATH, [_normalize_email_log(item) for item in logs][-5000:])


def load_release_info() -> Dict[str, object]:
    legacy_payload = _read_json(RELEASE_INFO_PATH, None)
    if isinstance(legacy_payload, dict) and legacy_payload.get("latest_version"):
        release = save_release_snapshot(legacy_payload)
        _write_json(RELEASE_INFO_PATH, release)
        return release
    release = get_release_snapshot()
    _write_json(RELEASE_INFO_PATH, release)
    return release


def save_release_info(payload: Dict[str, object]) -> Dict[str, object]:
    release = save_release_snapshot({**default_release_info(), **(payload or {})})
    _write_json(RELEASE_INFO_PATH, release)
    return release


def _decorate_license(item: Dict[str, object]) -> Dict[str, object]:
    admin = get_admin_by_id(str(item.get("admin_id") or "")) or {}
    license_item = dict(item)
    license_item["license_key"] = str(license_item.get("license_key") or f"LIC-{uuid4().hex[:24].upper()}")
    license_item["admin_id"] = str(license_item.get("admin_id") or "")
    license_item["tenant_id"] = _normalize_tenant_id(license_item.get("tenant_id") or admin.get("tenant_id"))
    license_item["server_ip"] = str(license_item.get("server_ip") or admin.get("server_ip") or "").strip()
    license_item["device_id"] = str(license_item.get("device_id") or "").strip()
    license_item["status"] = str(license_item.get("status") or "inactive").strip().lower() or "inactive"
    license_item["issued_at"] = str(license_item.get("issued_at") or utc_now_iso())
    license_item["activated_at"] = str(license_item.get("activated_at") or "")
    license_item["expires_at"] = str(license_item.get("expires_at") or admin.get("subscription_end_date") or "")
    license_item["activation_count"] = int(license_item.get("activation_count") or 0)
    license_item["activation_limit"] = int(license_item.get("activation_limit") or 1)
    license_item["subscription_plan"] = str(license_item.get("subscription_plan") or admin.get("plan_id") or "trial").strip().lower()
    license_item["app_version"] = str(license_item.get("app_version") or "").strip()
    license_item["last_validated_at"] = str(license_item.get("last_validated_at") or "")
    return license_item


def get_tenant_license(tenant_id: str) -> Optional[Dict[str, object]]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    licenses = [item for item in load_licenses() if _normalize_tenant_id(item.get("tenant_id")) == normalized_tenant_id]
    if not licenses:
        return None
    licenses.sort(key=lambda item: str(item.get("issued_at") or ""), reverse=True)
    return licenses[0]


def validate_tenant_license_access(*, tenant_id: str, server_ip: str = "") -> Dict[str, object]:
    tenant = get_tenant(tenant_id)
    if str(tenant.get("status") or "").strip().lower() == "blocked":
        raise ValueError("This tenant is locked.")
    if _normalize_tenant_id(tenant.get("tenant_id")) == MASTER_TENANT_ID:
        return {"valid": True, "tenant_id": tenant["tenant_id"], "license_key": ""}
    license_key = str(tenant.get("license_key") or "").strip().upper()
    if not license_key:
        return {"valid": True, "tenant_id": tenant["tenant_id"], "license_key": ""}
    license_item = next((item for item in load_licenses() if str(item.get("license_key") or "").strip().upper() == license_key), None)
    if license_item is None:
        raise ValueError("Tenant license not found.")
    if _normalize_tenant_id(license_item.get("tenant_id")) != _normalize_tenant_id(tenant["tenant_id"]):
        raise ValueError("Tenant license mismatch.")
    expires_at = parse_datetime(str(license_item.get("expires_at") or ""))
    if expires_at and expires_at < utc_now():
        raise ValueError("Tenant license expired.")
    required_server_ip = str(license_item.get("server_ip") or tenant.get("server_ip") or "").strip()
    if required_server_ip and server_ip and required_server_ip != str(server_ip).strip():
        raise ValueError("Tenant license server IP mismatch.")
    if str(license_item.get("status") or "").strip().lower() in {"revoked", "inactive", "expired"}:
        raise ValueError("Tenant license is not active.")
    return {"valid": True, "tenant_id": tenant["tenant_id"], "license_key": license_item["license_key"]}


def load_licenses() -> List[Dict[str, object]]:
    payload = _read_json(LICENSES_PATH, [])
    items = [_decorate_license(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    if items != payload:
        save_licenses(items)
    return items


def save_licenses(items: List[Dict[str, object]]) -> None:
    _write_json(LICENSES_PATH, [_decorate_license(item) for item in items][-5000:])


def get_admin_by_email(email: str) -> Optional[Dict[str, object]]:
    normalized = _normalize_email(email)
    return next((item for item in load_admins() if item.get("email") == normalized), None)


def get_admin_by_id(admin_id: str) -> Optional[Dict[str, object]]:
    return next((item for item in load_admins() if str(item.get("admin_id") or "") == str(admin_id or "")), None)


def get_admin_by_tenant_id(tenant_id: Optional[str]) -> Optional[Dict[str, object]]:
    normalized = _normalize_tenant_id(tenant_id)
    direct = next((item for item in load_admins() if _normalize_tenant_id(item.get("tenant_id")) == normalized), None)
    if direct is not None:
        return direct
    if normalized == MASTER_TENANT_ID:
        return next((item for item in load_admins() if _normalize_admin_role(item.get("role")) == "master"), None)
    return None


def _resolve_admin_id(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Optional[str]:
    normalized_admin_id = str(admin_id or "").strip()
    if normalized_admin_id:
        return normalized_admin_id
    admin = get_admin_by_tenant_id(tenant_id)
    if admin is not None:
        return str(admin.get("admin_id") or "").strip() or None
    return None


def get_admin_storage_path(admin_id: str) -> Path:
    normalized = str(admin_id or "").strip()
    if not normalized:
        raise ValueError("admin_id is required.")
    admin = get_admin_by_id(normalized) or {}
    if _normalize_admin_role(admin.get("role")) == "master":
        MASTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return MASTER_DATA_DIR
    return get_tenant_data_path(normalized)


def _find_admin_by_token(token: str) -> Optional[Dict[str, object]]:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        return None
    for admin in load_admins():
        if admin.get("api_token_hash") and secrets.compare_digest(
            str(admin.get("api_token_hash")),
            _hash_secret(normalized_token, str(admin.get("admin_id") or "")),
        ):
            return admin
    return None


def ensure_admin_tenant_storage(admin_id: str) -> Path:
    folder = get_admin_storage_path(admin_id)
    admin = get_admin_by_id(admin_id) or {}
    tenant = get_tenant(admin.get("tenant_id")) if admin.get("tenant_id") else _master_tenant_payload()
    defaults = {
        "providers.json": _tenant_default_provider_payload(),
        "provider_groups.json": [],
        "channels.json": [],
        "mobile_apps.json": [],
        "approved_streams.json": [],
        "football_metadata.json": _tenant_default_metadata(),
        "analytics.json": [],
        "meta.json": {},
        "branding.json": dict(tenant.get("branding") or _default_branding()),
    }
    for filename, payload in defaults.items():
        target = folder / filename
        if not target.exists():
            _write_json(target, payload)
    meta_path = folder / "meta.json"
    meta = _read_json(meta_path, {})
    if not isinstance(meta, dict):
        meta = {}
    meta.setdefault("setup_completed", False)
    meta.setdefault("mobile_api_token", secrets.token_urlsafe(24))
    meta.setdefault("admin_id", admin_id)
    _write_json(meta_path, meta)
    return folder


def _rebind_payload_tenant(payload, tenant_id: str):
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    if isinstance(payload, dict):
        if all(isinstance(payload.get(key), list) for key in ("nations", "competitions", "clubs")):
            rebound = {}
            for key in ("nations", "competitions", "clubs"):
                rebound[key] = []
                for item in payload.get(key, []):
                    if isinstance(item, dict):
                        rebound[key].append({**item, "tenant_id": normalized_tenant_id})
            return rebound
        return {
            key: (_rebind_payload_tenant(value, tenant_id) if isinstance(value, (dict, list)) else value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        rebound_items = []
        for item in payload:
            if isinstance(item, dict):
                rebound_items.append({**item, "tenant_id": normalized_tenant_id})
            else:
                rebound_items.append(item)
        return rebound_items
    return payload


def _replace_tenant_reference(payload, previous_tenant_id: str, next_tenant_id: str):
    previous = _normalize_tenant_id(previous_tenant_id)
    target = _normalize_tenant_id(next_tenant_id)
    if isinstance(payload, dict):
        rebound = {}
        for key, value in payload.items():
            if key == "tenant_id" and _normalize_tenant_id(value) == previous:
                rebound[key] = target
            else:
                rebound[key] = _replace_tenant_reference(value, previous, target)
        return rebound
    if isinstance(payload, list):
        return [_replace_tenant_reference(item, previous, target) for item in payload]
    return payload


def migrate_master_tenant_identity() -> None:
    raw_admins = _read_json(ADMINS_PATH, [])
    if not isinstance(raw_admins, list) or not raw_admins:
        return
    master_index = next(
        (
            index
            for index, item in enumerate(raw_admins)
            if isinstance(item, dict) and _normalize_admin_role(item.get("role"), default="") == "master"
        ),
        0,
    )
    master_raw = raw_admins[master_index] if isinstance(raw_admins[master_index], dict) else {}
    previous_tenant_id = _normalize_tenant_id(master_raw.get("tenant_id"))
    if previous_tenant_id == MASTER_TENANT_ID:
        ensure_admin_tenant_storage(str(master_raw.get("admin_id") or ""))
        return

    master_raw = {**master_raw, "role": "master", "tenant_id": MASTER_TENANT_ID}
    raw_admins[master_index] = master_raw
    save_admins(raw_admins)

    tenants = load_tenants()
    previous_tenant = next((item for item in tenants if item.get("tenant_id") == previous_tenant_id), None)
    current_master_tenant = next((item for item in tenants if item.get("tenant_id") == MASTER_TENANT_ID), None)
    merged_master_tenant = _decorate_tenant(
        {
            **(current_master_tenant or previous_tenant or _master_tenant_payload(str(master_raw.get("name") or "Master Platform"))),
            "tenant_id": MASTER_TENANT_ID,
            "name": str((previous_tenant or current_master_tenant or {}).get("name") or master_raw.get("name") or "Master Platform"),
        }
    )
    next_tenants = [item for item in tenants if item.get("tenant_id") not in {previous_tenant_id, MASTER_TENANT_ID}]
    next_tenants.append(merged_master_tenant)
    save_tenants(next_tenants)

    master_admin_id = str(master_raw.get("admin_id") or "").strip()
    if master_admin_id:
        previous_folder = TENANT_DATA_DIR / master_admin_id
        master_folder = ensure_admin_tenant_storage(master_admin_id)
        for filename in (
            "providers.json",
            "approved_streams.json",
            "football_metadata.json",
            "analytics.json",
            "meta.json",
            "branding.json",
            "app_versions.json",
        ):
            source = previous_folder / filename
            target = master_folder / filename
            if not source.exists() or source.resolve() == target.resolve():
                continue
            payload = _read_json(source, None)
            if payload is None:
                continue
            _write_json(target, _replace_tenant_reference(payload, previous_tenant_id, MASTER_TENANT_ID))

    for path in (USERS_PATH, SESSIONS_PATH, SECURITY_LOGS_PATH, VIEWERS_PATH):
        payload = _read_json(path, None)
        if payload is not None:
            _write_json(path, _replace_tenant_reference(payload, previous_tenant_id, MASTER_TENANT_ID))


def migrate_legacy_admin_data() -> None:
    legacy_files = {
        "providers.json": DATA_DIR / "providers.json",
        "approved_streams.json": APPROVED_STREAMS_PATH,
        "football_metadata.json": METADATA_PATH,
        "analytics.json": VIEWERS_PATH,
    }
    has_legacy_provider_config = CONFIG_PATH.exists()
    if not any(path.exists() for path in legacy_files.values()) and not has_legacy_provider_config:
        return

    admins = list_admins()
    if not admins:
        return

    root_admin = next((item for item in admins if _normalize_admin_role(item.get("role")) == "master"), admins[0])
    first_tenant_id = _normalize_tenant_id(root_admin.get("tenant_id"))
    tenant_folder = ensure_admin_tenant_storage(str(root_admin.get("admin_id") or ""))
    if has_legacy_provider_config:
        legacy_settings = load_config()
        if legacy_settings is not None:
            provider_target = tenant_folder / "providers.json"
            current_payload = _read_json(provider_target, [])
            if not current_payload:
                _write_json(
                    provider_target,
                    [{**_settings_to_dict(legacy_settings), "saved_at": utc_now_iso()}],
                )
    for filename, source in legacy_files.items():
        if not source.exists():
            continue
        target = tenant_folder / filename
        payload = _read_json(source, None)
        if payload is None:
            continue
        if filename in {"approved_streams.json", "football_metadata.json", "analytics.json"}:
            payload = _rebind_payload_tenant(payload, first_tenant_id)
        _write_json(target, payload)
        try:
            source.unlink()
        except OSError:
            pass


def _admin_public_payload(admin: Dict[str, object]) -> Dict[str, object]:
    tenant = get_branding_config(admin.get("tenant_id"))
    return {
        "admin_id": admin.get("admin_id"),
        "role": admin.get("role"),
        "tenant_id": admin.get("tenant_id"),
        "name": admin.get("name"),
        "email": admin.get("email"),
        "plan_id": admin.get("plan_id"),
        "status": admin.get("status"),
        "trial_days": admin.get("trial_days"),
        "subscription_status": admin.get("subscription_status"),
        "subscription_start": admin.get("subscription_start_date"),
        "subscription_start_date": admin.get("subscription_start_date"),
        "subscription_end_date": admin.get("subscription_end_date"),
        "subscription_end": admin.get("subscription_end_date") or admin.get("subscription_end"),
        "device_id": admin.get("device_id"),
        "server_id": admin.get("server_id"),
        "server_domain": admin.get("server_domain"),
        "server_ip": admin.get("server_ip"),
        "server_registered_at": admin.get("server_registered_at"),
        "branding_info": {
            "app_name": str(admin.get("branding_info", {}).get("app_name") or tenant.get("branding", {}).get("app_name") or tenant.get("name") or ""),
            "logo_url": str(admin.get("branding_info", {}).get("logo_url") or tenant.get("branding", {}).get("logo_url") or ""),
            "icon_url": str(admin.get("branding_info", {}).get("icon_url") or tenant.get("branding", {}).get("icon_url") or ""),
        },
        "created_at": admin.get("created_at"),
        "tenant": tenant,
    }


def admin_session_payload(admin: Dict[str, object]) -> Dict[str, object]:
    return _admin_public_payload(_decorate_admin(admin))


def issue_admin_api_token(admin_id: str) -> Dict[str, object]:
    admin = get_admin_by_id(admin_id)
    if admin is None:
        raise ValueError("Admin not found.")
    token = secrets.token_urlsafe(32)
    admin["api_token_hash"] = _hash_secret(token, str(admin["admin_id"]))
    admin["updated_at"] = utc_now_iso()
    payload = _replace_admin(admin)
    return {"token": token, "admin": _admin_public_payload(payload)}


def register_admin(
    *,
    name: str,
    email: str,
    password: str,
    plan_id: str,
    device_id: str,
    role: Optional[str] = None,
    payment_provider: str = "",
    payment_reference: str = "",
) -> Dict[str, object]:
    normalized_name = _normalize_name(name)
    normalized_email = _normalize_email(email)
    normalized_device_id = str(device_id or "").strip()
    if not normalized_name:
        raise ValueError("Name is required.")
    if not normalized_email:
        raise ValueError("Email is required.")
    if not password:
        raise ValueError("Password is required.")
    if not normalized_device_id:
        raise ValueError("device_id is required.")
    if get_admin_by_email(normalized_email):
        raise ValueError("An admin account already exists for this email.")

    existing_admins = list_admins()
    assigned_role = _normalize_admin_role(role, default="master" if not existing_admins else "client")
    if assigned_role not in {"master", "client"}:
        raise ValueError("role must be either master or client.")

    tenant_id = MASTER_TENANT_ID if assigned_role == "master" else _slugify(f"{normalized_name}-{uuid4().hex[:6]}")
    normalized_plan_id = "unlimited" if assigned_role == "master" else (str(plan_id or "trial").strip().lower() or "trial")
    upsert_tenant(
        tenant_id=tenant_id,
        name=normalized_name,
        email=normalized_email,
        subscription_plan=normalized_plan_id,
        status="active",
        admin_username="" if assigned_role == "master" else normalized_email,
        admin_password="" if assigned_role == "master" else password,
    )
    now = utc_now()
    salt = secrets.token_hex(16)
    admin = _decorate_admin(
        {
            "admin_id": uuid4().hex,
            "tenant_id": tenant_id,
            "name": normalized_name,
            "email": normalized_email,
            "plan_id": normalized_plan_id,
            "password_salt": salt,
            "password_hash": _hash_secret(password, salt),
            "subscription_started_at": now.isoformat(),
            "subscription_start_date": now.isoformat(),
            "subscription_end": "" if assigned_role == "master" else (now + _admin_subscription_delta(plan_id)).isoformat(),
            "subscription_end_date": "" if assigned_role == "master" else (now + _admin_subscription_delta(plan_id)).isoformat(),
            "subscription_status": "active" if assigned_role == "master" else ("trial" if str(plan_id or "trial").strip().lower() == "trial" else "active"),
            "status": "active",
            "role": assigned_role,
            "trial_days": 0 if assigned_role == "master" else (TRIAL_DAYS if str(plan_id or "trial").strip().lower() == "trial" else 0),
            "device_id": normalized_device_id,
            "device_transfer_available_at": "",
            "server_reset_available_at": "",
            "payment_provider": str(payment_provider or "").strip().lower(),
            "payment_reference": str(payment_reference or "").strip(),
            "last_payment_at": now.isoformat(),
            "branding_info": {
                "app_name": normalized_name,
                "logo_url": "",
            },
        }
    )
    save_admins([*load_admins(), admin])
    ensure_admin_tenant_storage(str(admin["admin_id"]))
    migrate_legacy_admin_data()
    token = issue_admin_api_token(str(admin["admin_id"]))
    return {"admin": token["admin"], "api_token": token["token"], "device_id": normalized_device_id}


def authenticate_admin(email: str, password: str, device_id: str) -> Dict[str, object]:
    admin = get_admin_by_email(email)
    logger.info(
        "Admin login lookup email=%s found=%s tenant_id=%s role=%s",
        _normalize_email(email),
        bool(admin),
        str((admin or {}).get("tenant_id") or ""),
        str((admin or {}).get("role") or ""),
    )
    if admin is None:
        raise ValueError("Invalid email or password.")
    is_master = _normalize_admin_role(admin.get("role"), default="client") == "master"
    expected = _hash_secret(password, str(admin.get("password_salt") or ""))
    if not secrets.compare_digest(expected, str(admin.get("password_hash") or "")):
        raise ValueError("Invalid email or password.")
    if not is_master and str(admin.get("status") or "").strip().lower() == "blocked":
        raise ValueError("This client account is blocked.")
    if not is_master and str(admin.get("subscription_status") or "") == "expired":
        raise ValueError("Subscription expired.")
    if not is_master:
        validate_tenant_license_access(
            tenant_id=str(admin.get("tenant_id") or ""),
            server_ip=str(admin.get("server_ip") or ""),
        )
    normalized_device_id = str(device_id or "").strip()
    if not normalized_device_id:
        raise ValueError("device_id is required.")
    if admin.get("device_id") and str(admin.get("device_id")) != normalized_device_id:
        if str(admin.get("role") or "").strip().lower() != "master":
            raise ValueError("This subscription is already bound to another desktop device.")
    admin["device_id"] = normalized_device_id
    payload = _replace_admin(admin)
    token = issue_admin_api_token(str(payload["admin_id"]))
    return {"admin": token["admin"], "api_token": token["token"], "device_id": normalized_device_id}


def validate_admin_api_token(token: str, *, device_id: str = "", server_id: str = "", require_server: bool = False) -> Dict[str, object]:
    admin = _find_admin_by_token(token)
    if admin is None:
        raise ValueError("Invalid admin token.")
    is_master = _normalize_admin_role(admin.get("role"), default="client") == "master"
    if not is_master and str(admin.get("status") or "").strip().lower() == "blocked":
        raise ValueError("This client account is blocked.")
    if not is_master and str(admin.get("subscription_status") or "") == "expired":
        raise ValueError("Subscription expired.")
    if not is_master:
        validate_tenant_license_access(
            tenant_id=str(admin.get("tenant_id") or ""),
            server_ip=str(admin.get("server_ip") or ""),
        )
    normalized_device_id = str(device_id or "").strip()
    normalized_server_id = str(server_id or "").strip()
    if admin.get("device_id") and normalized_device_id != str(admin.get("device_id")):
        raise ValueError("Desktop device mismatch.")
    if require_server and admin.get("server_id") and normalized_server_id != str(admin.get("server_id")):
        raise ValueError("Server mismatch.")
    if require_server and admin.get("server_id") and not normalized_server_id:
        raise ValueError("Server identifier required.")
    return _decorate_admin(admin)


def renew_admin_subscription(
    *,
    api_token: str,
    plan_id: str,
    payment_provider: str = "",
    payment_reference: str = "",
) -> Dict[str, object]:
    admin = _find_admin_by_token(api_token)
    if admin is None:
        raise ValueError("Invalid admin token.")

    normalized_plan_id = str(plan_id or "").strip().lower() or "1_year"
    now = utc_now()
    current_end = parse_datetime(str(admin.get("subscription_end") or ""))
    anchor = current_end if current_end and current_end > now else now
    next_end = anchor + _admin_subscription_delta(normalized_plan_id)

    admin["plan_id"] = normalized_plan_id
    admin["subscription_started_at"] = admin.get("subscription_started_at") or now.isoformat()
    admin["subscription_start_date"] = admin.get("subscription_start_date") or admin["subscription_started_at"]
    admin["subscription_end"] = next_end.isoformat()
    admin["subscription_end_date"] = next_end.isoformat()
    admin["subscription_status"] = "active"
    admin["status"] = "active"
    admin["payment_provider"] = str(payment_provider or admin.get("payment_provider") or "").strip().lower()
    admin["payment_reference"] = str(payment_reference or admin.get("payment_reference") or "").strip()
    admin["last_payment_at"] = now.isoformat()

    payload = _replace_admin(admin)
    update_tenant_record(
        str(admin.get("tenant_id") or ""),
        {
            "subscription_plan": normalized_plan_id,
            "status": "active",
            "email": str(admin.get("email") or ""),
            "server_ip": str(admin.get("server_ip") or ""),
        },
    )
    return _admin_public_payload(payload)


def _require_managed_admin(admin_id: str) -> Dict[str, object]:
    admin = get_admin_by_id(admin_id)
    if admin is None:
        raise ValueError("Client account not found.")
    if str(admin.get("role") or "") == "master":
        raise ValueError("The master account cannot be managed from this endpoint.")
    return admin


def block_platform_client(admin_id: str) -> Dict[str, object]:
    admin = _require_managed_admin(admin_id)
    admin["status"] = "blocked"
    update_tenant_record(str(admin.get("tenant_id") or ""), {"status": "blocked"})
    return _admin_public_payload(_replace_admin(admin))


def unblock_platform_client(admin_id: str) -> Dict[str, object]:
    admin = _require_managed_admin(admin_id)
    admin["status"] = "active"
    update_tenant_record(str(admin.get("tenant_id") or ""), {"status": "active"})
    return _admin_public_payload(_replace_admin(admin))


def extend_platform_client_trial_days(admin_id: str, extra_days: int) -> Dict[str, object]:
    admin = _require_managed_admin(admin_id)
    days = max(1, int(extra_days or 0))
    now = utc_now()
    current_end = parse_datetime(str(admin.get("subscription_end_date") or admin.get("subscription_end") or "")) or now
    anchor = current_end if current_end > now else now
    next_end = anchor + timedelta(days=days)
    admin["trial_days"] = int(admin.get("trial_days") or 0) + days
    admin["plan_id"] = "trial" if str(admin.get("plan_id") or "") == "trial" else admin.get("plan_id")
    admin["subscription_status"] = "trial"
    admin["subscription_end"] = next_end.isoformat()
    admin["subscription_end_date"] = next_end.isoformat()
    admin["status"] = "active"
    update_tenant_record(
        str(admin.get("tenant_id") or ""),
        {
            "subscription_plan": str(admin.get("plan_id") or "trial"),
            "status": "active",
            "email": str(admin.get("email") or ""),
            "server_ip": str(admin.get("server_ip") or ""),
        },
    )
    return _admin_public_payload(_replace_admin(admin))


def reset_platform_client_server_binding(admin_id: str) -> Dict[str, object]:
    admin = _require_managed_admin(admin_id)
    admin["server_id"] = ""
    admin["server_domain"] = ""
    admin["server_ip"] = ""
    admin["hardware_hash"] = ""
    admin["server_registered_at"] = ""
    admin["server_reset_available_at"] = ""
    meta = load_tenant_meta(admin_id=admin_id)
    meta["server_id"] = ""
    save_tenant_meta(meta, admin_id=admin_id)
    return _admin_public_payload(_replace_admin(admin))


def delete_platform_client(admin_id: str) -> Dict[str, object]:
    admin = _require_managed_admin(admin_id)
    save_admins([item for item in load_admins() if str(item.get("admin_id") or "") != admin_id])
    tenant_folder = get_tenant_data_path(admin_id)
    if tenant_folder.exists():
        shutil.rmtree(tenant_folder, ignore_errors=True)
    save_install_logs([item for item in load_install_logs() if str(item.get("admin_id") or "") != admin_id])
    save_subscription_logs([item for item in load_subscription_logs() if str(item.get("admin_id") or "") != admin_id])
    save_audit_logs([item for item in load_audit_logs() if str(item.get("admin_id") or "") != admin_id])
    save_email_logs([item for item in load_email_logs() if str(item.get("admin_id") or "") != admin_id])
    save_licenses([item for item in load_licenses() if str(item.get("admin_id") or "") != admin_id])
    tenants = [item for item in load_tenants() if str(item.get("tenant_id") or "") != str(admin.get("tenant_id") or "")]
    save_tenants(tenants)
    return {"deleted": True, "admin_id": admin_id}


def register_install_event(*, admin_id: str, device_id: str, app_version: str, timestamp: str = "") -> Dict[str, object]:
    admin = get_admin_by_id(admin_id)
    if admin is None:
        raise ValueError("Admin not found.")
    entry = _normalize_install_log(
        {
            "id": uuid4().hex,
            "admin_id": str(admin_id),
            "tenant_id": str(admin.get("tenant_id") or ""),
            "device_id": str(device_id or "").strip(),
            "app_version": str(app_version or "").strip(),
            "subscription_status": str(admin.get("subscription_status") or "unknown"),
            "install_timestamp": str(timestamp or utc_now_iso()),
            "admin_name": str(admin.get("name") or ""),
            "admin_email": str(admin.get("email") or ""),
            "platform": "desktop",
        }
    )
    logs = load_install_logs()
    logs.append(entry)
    save_install_logs(logs)
    return entry


def register_subscription_event(
    *,
    admin_id: str,
    subscription_plan: str,
    start_date: str,
    end_date: str,
) -> Dict[str, object]:
    admin = get_admin_by_id(admin_id)
    if admin is None:
        raise ValueError("Admin not found.")
    entry = _normalize_subscription_log(
        {
            "id": uuid4().hex,
            "admin_id": str(admin_id),
            "tenant_id": str(admin.get("tenant_id") or ""),
            "subscription_plan": str(subscription_plan or "").strip(),
            "start_date": str(start_date or admin.get("subscription_start_date") or ""),
            "end_date": str(end_date or admin.get("subscription_end_date") or ""),
            "timestamp": utc_now_iso(),
            "subscription_status": str(admin.get("subscription_status") or "unknown"),
            "admin_name": str(admin.get("name") or ""),
            "admin_email": str(admin.get("email") or ""),
        }
    )
    logs = load_subscription_logs()
    logs.append(entry)
    save_subscription_logs(logs)
    return entry


def get_install_stats() -> Dict[str, object]:
    installs = load_install_logs()
    subscriptions = load_subscription_logs()
    client_admin_ids = {
        str(item.get("admin_id") or "")
        for item in list_admins()
        if _normalize_admin_role(item.get("role")) != "master"
    }
    installs = [item for item in installs if str(item.get("admin_id") or "") in client_admin_ids]
    subscriptions = [item for item in subscriptions if str(item.get("admin_id") or "") in client_admin_ids]
    by_admin: Dict[str, Dict[str, object]] = {}

    for entry in installs:
        bucket = by_admin.setdefault(
            str(entry.get("admin_id") or ""),
            {
                "admin_id": str(entry.get("admin_id") or ""),
                "tenant_id": str(entry.get("tenant_id") or ""),
                "install_count": 0,
                "unique_devices": set(),
                "subscription_count": 0,
                "active_subscription_count": 0,
                "estimated_revenue": 0.0,
                "admin_email": str(entry.get("admin_email") or ""),
                "admin_name": str(entry.get("admin_name") or ""),
                "latest_app_version": "",
            },
        )
        bucket["install_count"] = int(bucket["install_count"]) + 1
        bucket["unique_devices"].add(str(entry.get("device_id") or ""))
        bucket["latest_app_version"] = str(entry.get("app_version") or bucket.get("latest_app_version") or "")

    for entry in subscriptions:
        bucket = by_admin.setdefault(
            str(entry.get("admin_id") or ""),
            {
                "admin_id": str(entry.get("admin_id") or ""),
                "tenant_id": str(entry.get("tenant_id") or ""),
                "install_count": 0,
                "unique_devices": set(),
                "subscription_count": 0,
                "active_subscription_count": 0,
                "estimated_revenue": 0.0,
                "admin_email": str(entry.get("admin_email") or ""),
                "admin_name": str(entry.get("admin_name") or ""),
                "latest_app_version": "",
            },
        )
        bucket["subscription_count"] = int(bucket["subscription_count"]) + 1
        if str(entry.get("subscription_status") or "").lower() == "active":
            bucket["active_subscription_count"] = int(bucket["active_subscription_count"]) + 1
        bucket["estimated_revenue"] = float(bucket["estimated_revenue"]) + float(entry.get("estimated_revenue") or 0.0)

    items = []
    for value in by_admin.values():
        items.append(
            {
                "admin_id": value["admin_id"],
                "tenant_id": value["tenant_id"],
                "admin_name": value["admin_name"],
                "admin_email": value["admin_email"],
                "install_count": value["install_count"],
                "unique_devices": len(value["unique_devices"]),
                "subscription_count": value["subscription_count"],
                "active_subscription_count": value["active_subscription_count"],
                "estimated_revenue": round(float(value["estimated_revenue"]), 2),
                "latest_app_version": value["latest_app_version"],
            }
        )
    items.sort(key=lambda item: item["install_count"], reverse=True)
    return {
        "items": items,
        "totals": {
            "install_count": len(installs),
            "unique_devices": len({str(item.get("device_id") or "") for item in installs}),
            "subscription_count": len(subscriptions),
            "active_subscription_count": sum(int(item.get("active_subscription_count") or 0) for item in items),
            "estimated_revenue": round(sum(float(item.get("estimated_revenue") or 0.0) for item in items), 2),
        },
    }


def get_subscription_stats(*, admin_id: Optional[str] = None) -> Dict[str, object]:
    subscriptions = load_subscription_logs()
    if admin_id:
        subscriptions = [item for item in subscriptions if str(item.get("admin_id") or "") == str(admin_id)]
    installs = load_install_logs()
    if admin_id:
        installs = [item for item in installs if str(item.get("admin_id") or "") == str(admin_id)]
    latest_subscriptions = {}
    for item in subscriptions:
        latest_subscriptions[str(item.get("admin_id") or "")] = item
    active_count = sum(1 for item in latest_subscriptions.values() if str(item.get("subscription_status") or "").lower() == "active")
    return {
        "items": subscriptions,
        "totals": {
            "install_count": len(installs),
            "subscription_count": len(subscriptions),
            "active_subscription_count": active_count,
            "estimated_revenue": round(sum(float(item.get("estimated_revenue") or 0.0) for item in subscriptions), 2),
        },
    }


def get_white_label_dashboard(*, admin_id: Optional[str] = None) -> Dict[str, object]:
    installs = load_install_logs()
    subscriptions = load_subscription_logs()
    audits = load_audit_logs()
    if admin_id:
        installs = [item for item in installs if str(item.get("admin_id") or "") == str(admin_id)]
        subscriptions = [item for item in subscriptions if str(item.get("admin_id") or "") == str(admin_id)]
        audits = [item for item in audits if str(item.get("admin_id") or "") == str(admin_id)]
    else:
        client_admin_ids = {
            str(item.get("admin_id") or "")
            for item in list_admins()
            if _normalize_admin_role(item.get("role")) != "master"
        }
        installs = [item for item in installs if str(item.get("admin_id") or "") in client_admin_ids]
        subscriptions = [item for item in subscriptions if str(item.get("admin_id") or "") in client_admin_ids]
        audits = [item for item in audits if str(item.get("admin_id") or "") in client_admin_ids]
    install_stats = get_install_stats()
    if admin_id:
        install_stats["items"] = [item for item in install_stats["items"] if str(item.get("admin_id") or "") == str(admin_id)]
        selected = install_stats["items"][0] if install_stats["items"] else None
        install_stats["totals"] = selected or {
            "admin_id": admin_id,
            "install_count": len(installs),
            "unique_devices": len({str(item.get("device_id") or "") for item in installs}),
            "subscription_count": len(subscriptions),
            "active_subscription_count": 0,
            "estimated_revenue": round(sum(float(item.get("estimated_revenue") or 0.0) for item in subscriptions), 2),
        }
    return {
        "summary": install_stats["totals"],
        "installs": installs[-200:],
        "subscriptions": subscriptions[-200:],
        "audit_logs": audits[-200:],
        "release": load_release_info(),
        "apk_management": {
            "items": list_apk_versions(),
            "latest": get_latest_apk_version(),
        },
    }


def get_platform_client_dashboard(*, admin_id: Optional[str] = None) -> Dict[str, object]:
    return get_white_label_dashboard(admin_id=admin_id)


def check_for_desktop_update(current_version: str, *, platform: str = "") -> Dict[str, object]:
    release = load_release_info()
    latest_version = str(release.get("latest_version") or "0.1.0")
    current = str(current_version or "").strip() or "0.0.0"
    has_update = _version_key(latest_version) > _version_key(current)
    minimum_supported = str(release.get("minimum_supported_version") or latest_version)
    return {
        "current_version": current,
        "latest_version": latest_version,
        "has_update": has_update,
        "is_supported": _version_key(current) >= _version_key(minimum_supported),
        "download_url": str(release.get("download_url") or ""),
        "release_notes": str(release.get("release_notes") or ""),
        "published_at": str(release.get("published_at") or ""),
        "platform": str(platform or ""),
    }


def log_audit_event(
    *,
    path: str,
    method: str,
    status_code: int,
    admin_id: str = "",
    tenant_id: str = "",
    device_id: str = "",
    server_id: str = "",
    scope: str = "",
    duration_ms: int = 0,
) -> Dict[str, object]:
    global _AUDIT_LOG_BUFFER
    entry = _normalize_audit_log(
        {
            "id": uuid4().hex,
            "timestamp": utc_now_iso(),
            "path": path,
            "method": method,
            "status_code": status_code,
            "admin_id": admin_id,
            "tenant_id": tenant_id,
            "device_id": device_id,
            "server_id": server_id,
            "scope": scope,
            "duration_ms": duration_ms,
        }
    )
    _AUDIT_LOG_BUFFER.append(entry)
    flush_audit_logs()
    return entry


def log_email_event(
    *,
    admin_id: str,
    tenant_id: str,
    email: str,
    subject: str,
    status: str,
    detail: str = "",
    email_type: str = "subscription_reminder",
) -> Dict[str, object]:
    entry = _normalize_email_log(
        {
            "id": uuid4().hex,
            "type": email_type,
            "timestamp": utc_now_iso(),
            "admin_id": admin_id,
            "tenant_id": tenant_id,
            "email": email,
            "subject": subject,
            "status": status,
            "detail": detail,
        }
    )
    logs = load_email_logs()
    logs.append(entry)
    save_email_logs(logs)
    return entry


def admins_with_expiring_subscriptions(*, within_days: int = 7) -> List[Dict[str, object]]:
    now = utc_now()
    deadline = now + timedelta(days=max(1, int(within_days or 1)))
    items = []
    for admin in list_admins():
        end = parse_datetime(str(admin.get("subscription_end_date") or admin.get("subscription_end") or ""))
        if end is None:
            continue
        if now <= end <= deadline:
            items.append(admin)
    return items


def register_admin_server(*, api_token: str, server_domain: str, server_ip: str, hardware_hash: str, device_id: str = "") -> Dict[str, object]:
    admin = validate_admin_api_token(api_token, device_id=device_id, require_server=False)
    if admin.get("server_id"):
        raise ValueError("Server already registered.")
    admin["server_id"] = str(uuid4())
    admin["server_domain"] = str(server_domain or "").strip()
    admin["server_ip"] = str(server_ip or "").strip()
    admin["hardware_hash"] = str(hardware_hash or "").strip()
    admin["server_registered_at"] = utc_now_iso()
    admin["server_reset_available_at"] = (utc_now() + timedelta(hours=24)).isoformat()
    payload = _replace_admin(admin)
    update_tenant_record(str(admin.get("tenant_id") or ""), {"server_ip": str(admin.get("server_ip") or "")})
    return _admin_public_payload(payload)


def reset_admin_server(*, api_token: str, device_id: str = "") -> Dict[str, object]:
    admin = validate_admin_api_token(api_token, device_id=device_id, require_server=False)
    available_at = parse_datetime(str(admin.get("server_reset_available_at") or ""))
    now = utc_now()
    if available_at and available_at > now:
        raise ValueError("Server reset is allowed only once every 24 hours.")
    admin["server_id"] = ""
    admin["server_domain"] = ""
    admin["server_ip"] = ""
    admin["hardware_hash"] = ""
    admin["server_registered_at"] = ""
    admin["server_reset_available_at"] = (now + timedelta(hours=24)).isoformat()
    payload = _replace_admin(admin)
    update_tenant_record(str(admin.get("tenant_id") or ""), {"server_ip": ""})
    return _admin_public_payload(payload)


def transfer_admin_device(*, api_token: str, next_device_id: str) -> Dict[str, object]:
    admin = validate_admin_api_token(api_token, require_server=False)
    normalized_device_id = str(next_device_id or "").strip()
    if not normalized_device_id:
        raise ValueError("device_id is required.")
    available_at = parse_datetime(str(admin.get("device_transfer_available_at") or ""))
    now = utc_now()
    if available_at and available_at > now:
        raise ValueError("Device transfer is allowed only once every 24 hours.")
    admin["device_id"] = normalized_device_id
    admin["device_transfer_available_at"] = (now + timedelta(hours=24)).isoformat()
    payload = _replace_admin(admin)
    token = issue_admin_api_token(str(payload["admin_id"]))
    return {"admin": token["admin"], "api_token": token["token"], "device_id": normalized_device_id}


def _settings_to_dict(settings: IPTVSettings) -> dict:
    if hasattr(settings, "model_dump"):
        return settings.model_dump()
    return settings.dict()


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "item"


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, payload) -> None:
    _ensure_data_dir()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_config(settings: IPTVSettings) -> None:
    _write_json(CONFIG_PATH, _settings_to_dict(settings))


def load_config() -> Optional[IPTVSettings]:
    payload = _read_json(CONFIG_PATH, None)
    if payload is None:
        return None
    try:
        return IPTVSettings(**payload)
    except Exception:
        return None


def save_provider_settings(settings: IPTVSettings, *, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> None:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    if not resolved_admin_id:
        save_config(settings)
        return
    raw_payload = {
        **_settings_to_dict(settings),
        "saved_at": utc_now_iso(),
    }
    payload = [_normalize_provider_record(raw_payload, tenant_id=tenant_id)]
    _write_json(_tenant_file_path(resolved_admin_id, "providers.json"), payload)


def load_provider_settings(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Optional[IPTVSettings]:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    if not resolved_admin_id:
        return load_config()
    payload = _read_json(_tenant_file_path(resolved_admin_id, "providers.json"), [])
    if not isinstance(payload, list) or not payload:
        return None
    current = payload[0] if isinstance(payload[0], dict) else None
    if current is None:
        return None
    valid_fields = set(getattr(IPTVSettings, "model_fields", {}).keys()) or set(getattr(IPTVSettings, "__fields__", {}).keys())
    filtered = {key: value for key, value in current.items() if key in valid_fields}
    try:
        return IPTVSettings(**filtered)
    except Exception:
        return None


def list_provider_records(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    items = _load_tenant_table(admin_id=admin_id, tenant_id=tenant_id, table_name="providers.json")
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    records = [_normalize_provider_record(item, tenant_id=normalized_tenant_id) for item in items]
    return [item for item in records if item.get("tenant_id") == normalized_tenant_id]


def get_provider_record(provider_id: str, *, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Optional[Dict[str, object]]:
    normalized_provider_id = str(provider_id or "active").strip() or "active"
    return next((item for item in list_provider_records(admin_id=admin_id, tenant_id=tenant_id) if str(item.get("provider_id") or "") == normalized_provider_id), None)


def sync_provider_catalog(
    *,
    provider_id: str,
    streams: List[Dict[str, object]],
    admin_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, List[Dict[str, object]]]:
    provider = get_provider_record(provider_id, admin_id=admin_id, tenant_id=tenant_id)
    if provider is None or str(provider.get("status") or "") != "active":
        _save_tenant_table([], admin_id=admin_id, tenant_id=tenant_id, table_name="provider_groups.json")
        _save_tenant_table([], admin_id=admin_id, tenant_id=tenant_id, table_name="channels.json")
        return {"groups": [], "channels": []}

    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for stream in streams:
        group_name = str(stream.get("group") or "Ungrouped").strip() or "Ungrouped"
        grouped.setdefault(group_name, []).append(stream)

    groups: List[Dict[str, object]] = []
    channels: List[Dict[str, object]] = []
    for group_name in sorted(grouped.keys()):
        group_id = _slugify(f"{provider_id}-{group_name}")
        channels_for_group = grouped[group_name]
        groups.append(
            _normalize_provider_group_record(
                {
                    "group_id": group_id,
                    "tenant_id": normalized_tenant_id,
                    "provider_id": provider_id,
                    "group_name": group_name,
                    "channel_count": len(channels_for_group),
                },
                tenant_id=normalized_tenant_id,
            )
        )
        for stream in channels_for_group:
            channels.append(
                _normalize_channel_record(
                    {
                        **stream,
                        "group_id": group_id,
                        "provider_id": provider_id,
                        "tenant_id": normalized_tenant_id,
                    },
                    tenant_id=normalized_tenant_id,
                )
            )

    _save_tenant_table(groups, admin_id=admin_id, tenant_id=tenant_id, table_name="provider_groups.json")
    _save_tenant_table(channels, admin_id=admin_id, tenant_id=tenant_id, table_name="channels.json")
    return {"groups": groups, "channels": channels}


def list_provider_groups(*, provider_id: str, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    provider = get_provider_record(provider_id, admin_id=admin_id, tenant_id=tenant_id)
    if provider is None or str(provider.get("status") or "") != "active":
        return []
    items = _load_tenant_table(admin_id=admin_id, tenant_id=tenant_id, table_name="provider_groups.json")
    return [
        _normalize_provider_group_record(item, tenant_id=tenant_id)
        for item in items
        if str(item.get("provider_id") or "") == str(provider_id or "")
    ]


def list_group_channels(*, group_id: str, provider_id: str, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    provider = get_provider_record(provider_id, admin_id=admin_id, tenant_id=tenant_id)
    if provider is None or str(provider.get("status") or "") != "active":
        return []
    items = _load_tenant_table(admin_id=admin_id, tenant_id=tenant_id, table_name="channels.json")
    normalized_group_id = str(group_id or "").strip()
    return [
        _normalize_channel_record(item, tenant_id=tenant_id)
        for item in items
        if str(item.get("provider_id") or "") == str(provider_id or "")
        and str(item.get("group_id") or "") == normalized_group_id
    ]


def list_mobile_apps(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    items = _load_tenant_table(admin_id=admin_id, tenant_id=tenant_id, table_name="mobile_apps.json")
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    records = [_normalize_mobile_app_record(item, tenant_id=normalized_tenant_id) for item in items]
    return [item for item in records if item.get("tenant_id") == normalized_tenant_id]


def get_mobile_app(*, tenant_id: Optional[str] = None, admin_id: Optional[str] = None) -> Optional[Dict[str, object]]:
    items = list_mobile_apps(admin_id=admin_id, tenant_id=tenant_id)
    if not items:
        return None
    items.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    return items[0]


def save_mobile_app_record(
    *,
    tenant_id: str,
    package_id: str,
    app_name: str,
    logo_url: str,
    theme_color: str,
    generated_at: Optional[str] = None,
    artifact_name: str = "",
    build_id: str = "",
) -> Dict[str, object]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    record = _normalize_mobile_app_record(
        {
            "tenant_id": normalized_tenant_id,
            "package_id": package_id,
            "app_name": app_name,
            "logo_url": logo_url,
            "theme_color": theme_color,
            "generated_at": generated_at or utc_now_iso(),
            "artifact_name": artifact_name,
            "build_id": build_id,
        },
        tenant_id=normalized_tenant_id,
    )
    items = [item for item in list_mobile_apps(tenant_id=normalized_tenant_id) if str(item.get("package_id") or "") != str(record.get("package_id") or "")]
    items.append(record)
    _save_tenant_table(items, tenant_id=normalized_tenant_id, table_name="mobile_apps.json")
    return record


def load_metadata(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, List[Dict[str, object]]]:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    path = _tenant_file_path(resolved_admin_id, "football_metadata.json") if resolved_admin_id else METADATA_PATH
    payload = _read_json(path, _tenant_default_metadata())
    if not isinstance(payload, dict):
        return _tenant_default_metadata()
    for key in ("nations", "competitions", "clubs", "competition_club_links"):
        if not isinstance(payload.get(key), list):
            payload[key] = []
        normalized_items = []
        for item in payload[key]:
            if not isinstance(item, dict):
                continue
            current = dict(item)
            current["tenant_id"] = _normalize_tenant_id(current.get("tenant_id"))
            if key == "competition_club_links":
                current["competition_id"] = str(current.get("competition_id") or "").strip()
                raw_club_ids = current.get("club_ids")
                if not isinstance(raw_club_ids, list):
                    raw_club_ids = []
                current["club_ids"] = [str(club_id).strip() for club_id in raw_club_ids if str(club_id).strip()]
            if key == "competitions":
                current["participant_type"] = {
                    "clubs": "club",
                    "club": "club",
                    "nations": "nation",
                    "nation": "nation",
                }.get(str(current.get("participant_type") or "club").strip().lower() or "club", "club")
            normalized_items.append(current)
        payload[key] = normalized_items

    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    link_index: Dict[str, Dict[str, object]] = {
        str(item.get("competition_id") or ""): item
        for item in payload["competition_club_links"]
        if item.get("tenant_id") == normalized_tenant_id and str(item.get("competition_id") or "").strip()
    }
    migrated = False
    for club in payload["clubs"]:
        if club.get("tenant_id") != normalized_tenant_id:
            continue
        legacy_competition_id = str(club.get("competition_id") or "").strip()
        if not legacy_competition_id:
            continue
        link = link_index.setdefault(
            legacy_competition_id,
            {
                "competition_id": legacy_competition_id,
                "club_ids": [],
                "tenant_id": normalized_tenant_id,
            },
        )
        if str(club.get("id") or "").strip() and str(club.get("id")) not in link["club_ids"]:
            link["club_ids"].append(str(club.get("id")))
            migrated = True
        if club.get("competition_id"):
            club["competition_id"] = ""
            migrated = True
    if migrated:
        payload["competition_club_links"] = list(link_index.values()) + [
            item for item in payload["competition_club_links"]
            if item.get("tenant_id") != normalized_tenant_id
        ]
    return payload


def save_metadata(metadata: Dict[str, List[Dict[str, object]]], *, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> None:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    path = _tenant_file_path(resolved_admin_id, "football_metadata.json") if resolved_admin_id else METADATA_PATH
    _write_json(path, metadata)


def _competition_club_ids(metadata: Dict[str, List[Dict[str, object]]], competition_id: str, *, tenant_id: Optional[str] = None) -> List[str]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    for item in metadata.get("competition_club_links", []):
        if item.get("tenant_id") != normalized_tenant_id:
            continue
        if str(item.get("competition_id") or "") == str(competition_id or ""):
            return [str(club_id) for club_id in item.get("club_ids", []) if str(club_id).strip()]
    return []


def _set_competition_club_ids(metadata: Dict[str, List[Dict[str, object]]], competition_id: str, club_ids: List[str], *, tenant_id: Optional[str] = None) -> None:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    normalized_competition_id = str(competition_id or "").strip()
    normalized_club_ids: List[str] = []
    for club_id in club_ids:
        normalized_club_id = str(club_id or "").strip()
        if normalized_club_id and normalized_club_id not in normalized_club_ids:
            normalized_club_ids.append(normalized_club_id)

    next_links: List[Dict[str, object]] = []
    replaced = False
    for item in metadata.get("competition_club_links", []):
        if item.get("tenant_id") == normalized_tenant_id and str(item.get("competition_id") or "") == normalized_competition_id:
            if normalized_club_ids:
                next_links.append({
                    "competition_id": normalized_competition_id,
                    "club_ids": normalized_club_ids,
                    "tenant_id": normalized_tenant_id,
                })
            replaced = True
            continue
        next_links.append(item)
    if not replaced and normalized_club_ids:
        next_links.append({
            "competition_id": normalized_competition_id,
            "club_ids": normalized_club_ids,
            "tenant_id": normalized_tenant_id,
        })
    metadata["competition_club_links"] = next_links


def list_competition_club_links(*, competition_ids: Optional[List[str]] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    metadata = load_metadata(tenant_id=tenant_id)
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    allowed_ids = {str(item).strip() for item in (competition_ids or []) if str(item).strip()}
    links = [
        {
            "competition_id": str(item.get("competition_id") or ""),
            "club_ids": [str(club_id) for club_id in item.get("club_ids", []) if str(club_id).strip()],
            "tenant_id": normalized_tenant_id,
        }
        for item in metadata.get("competition_club_links", [])
        if item.get("tenant_id") == normalized_tenant_id
    ]
    if allowed_ids:
        links = [item for item in links if item["competition_id"] in allowed_ids]
    return links


def list_nations(tenant_id: Optional[str] = None) -> List[Dict[str, str]]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    return sorted(
        [item for item in load_metadata(tenant_id=tenant_id)["nations"] if item.get("tenant_id") == normalized_tenant_id],
        key=lambda item: item.get("name", "").lower(),
    )


def list_competitions(nation_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    metadata = load_metadata(tenant_id=tenant_id)
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    items = [item for item in metadata["competitions"] if item.get("tenant_id") == normalized_tenant_id]
    if nation_id:
        items = [item for item in items if item.get("nation_id") == nation_id]
    enriched = [
        {
            **item,
            "club_ids": _competition_club_ids(metadata, str(item.get("id") or ""), tenant_id=normalized_tenant_id),
        }
        for item in items
    ]
    return sorted(enriched, key=lambda item: item.get("name", "").lower())


def list_clubs(
    nation_id: Optional[str] = None,
    competition_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> List[Dict[str, object]]:
    metadata = load_metadata(tenant_id=tenant_id)
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    items = [item for item in metadata["clubs"] if item.get("tenant_id") == normalized_tenant_id]
    if nation_id:
        items = [item for item in items if item.get("nation_id") == nation_id]
    if competition_id:
        allowed_club_ids = set(_competition_club_ids(metadata, competition_id, tenant_id=normalized_tenant_id))
        items = [item for item in items if str(item.get("id") or "") in allowed_club_ids]
    return sorted(
        [
            {
                **item,
                "competition_ids": [
                    str(competition.get("id") or "")
                    for competition in metadata["competitions"]
                    if str(item.get("id") or "") in _competition_club_ids(metadata, str(competition.get("id") or ""), tenant_id=normalized_tenant_id)
                ],
            }
            for item in items
        ],
        key=lambda item: item.get("name", "").lower(),
    )


def get_nation(nation_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, str]]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    return next((item for item in load_metadata(tenant_id=tenant_id)["nations"] if item.get("id") == nation_id and item.get("tenant_id") == normalized_tenant_id), None)


def get_competition(competition_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, str]]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    return next(
        (item for item in load_metadata(tenant_id=tenant_id)["competitions"] if item.get("id") == competition_id and item.get("tenant_id") == normalized_tenant_id),
        None,
    )


def get_club(club_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, str]]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    return next((item for item in load_metadata(tenant_id=tenant_id)["clubs"] if item.get("id") == club_id and item.get("tenant_id") == normalized_tenant_id), None)


def _upsert_entity(collection_name: str, item: Dict[str, str], *, tenant_id: Optional[str] = None, admin_id: Optional[str] = None) -> Dict[str, str]:
    metadata = load_metadata(admin_id=admin_id, tenant_id=tenant_id)
    items = metadata[collection_name]
    entity_id = item.get("id") or uuid4().hex
    payload = {**item, "id": entity_id}
    existing_index = next(
        (index for index, current in enumerate(items) if current.get("id") == entity_id),
        None,
    )
    if existing_index is None:
        items.append(payload)
    else:
        items[existing_index] = payload
    metadata[collection_name] = items
    save_metadata(metadata, admin_id=admin_id, tenant_id=tenant_id)
    return payload


def upsert_nation(name: str, logo_url: str = "", nation_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, str]:
    normalized_name = _normalize_name(name)
    if not normalized_name:
        raise ValueError("Nation name is required.")
    return _upsert_entity(
        "nations",
        {
            "id": nation_id or "",
            "name": normalized_name,
            "slug": _slugify(normalized_name),
            "logo_url": logo_url.strip(),
            "tenant_id": _normalize_tenant_id(tenant_id),
        },
        tenant_id=tenant_id,
    )


def upsert_competition(
    name: str,
    nation_id: str,
    competition_type: str,
    logo_url: str = "",
    club_ids: Optional[List[str]] = None,
    participant_type: str = "club",
    competition_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, object]:
    normalized_name = _normalize_name(name)
    if not normalized_name:
        raise ValueError("Competition name is required.")
    if not nation_id:
        raise ValueError("Competition must belong to a nation.")
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    if get_nation(nation_id, tenant_id=normalized_tenant_id) is None:
        raise ValueError("Nation not found.")
    normalized_type = competition_type.strip().lower() or "league"
    if normalized_type not in {"league", "cup"}:
        raise ValueError("Competition type must be 'league' or 'cup'.")
    normalized_participant_type = str(participant_type or "club").strip().lower() or "club"
    normalized_participant_type = {
        "clubs": "club",
        "club": "club",
        "nations": "nation",
        "nation": "nation",
    }.get(normalized_participant_type, normalized_participant_type)
    if normalized_participant_type not in {"club", "nation"}:
        raise ValueError("Competition participant type must be 'club' or 'nation'.")
    payload = _upsert_entity(
        "competitions",
        {
            "id": competition_id or "",
            "name": normalized_name,
            "slug": _slugify(normalized_name),
            "nation_id": nation_id,
            "type": normalized_type,
            "participant_type": normalized_participant_type,
            "logo_url": logo_url.strip(),
            "tenant_id": normalized_tenant_id,
        },
        tenant_id=tenant_id,
    )
    metadata = load_metadata(tenant_id=tenant_id)
    selected_club_ids = club_ids if club_ids is not None else _competition_club_ids(metadata, str(payload.get("id") or ""), tenant_id=normalized_tenant_id)
    valid_club_ids = []
    for selected_club_id in selected_club_ids:
        club = get_club(str(selected_club_id), tenant_id=normalized_tenant_id)
        if club is None:
            continue
        valid_club_ids.append(str(club.get("id") or ""))
    _set_competition_club_ids(
        metadata,
        str(payload.get("id") or ""),
        valid_club_ids if normalized_participant_type == "club" else [],
        tenant_id=normalized_tenant_id,
    )
    save_metadata(metadata, tenant_id=tenant_id)
    return {
        **payload,
        "club_ids": valid_club_ids if normalized_participant_type == "club" else [],
    }


def upsert_club(
    name: str,
    nation_id: Optional[str] = None,
    logo_url: str = "",
    club_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, object]:
    normalized_name = _normalize_name(name)
    if not normalized_name:
        raise ValueError("Club name is required.")
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    normalized_nation_id = str(nation_id or "").strip()
    if normalized_nation_id and get_nation(normalized_nation_id, tenant_id=normalized_tenant_id) is None:
        raise ValueError("Nation not found.")
    return _upsert_entity(
        "clubs",
        {
            "id": club_id or "",
            "name": normalized_name,
            "slug": _slugify(normalized_name),
            "nation_id": normalized_nation_id,
            "logo_url": logo_url.strip(),
            "tenant_id": normalized_tenant_id,
        },
        tenant_id=tenant_id,
    )


def delete_nation(nation_id: str, tenant_id: Optional[str] = None) -> None:
    metadata = load_metadata(tenant_id=tenant_id)
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    if any(item.get("nation_id") == nation_id and item.get("tenant_id") == normalized_tenant_id for item in metadata["competitions"]):
        raise ValueError("Delete competitions for this nation first.")
    if any(item.get("nation_id") == nation_id and item.get("tenant_id") == normalized_tenant_id for item in metadata["clubs"]):
        raise ValueError("Delete or move clubs for this nation first.")
    metadata["nations"] = [item for item in metadata["nations"] if not (item.get("id") == nation_id and item.get("tenant_id") == normalized_tenant_id)]
    save_metadata(metadata, tenant_id=tenant_id)


def delete_competition(competition_id: str, tenant_id: Optional[str] = None) -> None:
    metadata = load_metadata(tenant_id=tenant_id)
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    metadata["competitions"] = [
        item for item in metadata["competitions"] if not (item.get("id") == competition_id and item.get("tenant_id") == normalized_tenant_id)
    ]
    _set_competition_club_ids(metadata, competition_id, [], tenant_id=normalized_tenant_id)
    save_metadata(metadata, tenant_id=tenant_id)


def delete_club(club_id: str, tenant_id: Optional[str] = None) -> None:
    metadata = load_metadata(tenant_id=tenant_id)
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    metadata["clubs"] = [item for item in metadata["clubs"] if not (item.get("id") == club_id and item.get("tenant_id") == normalized_tenant_id)]
    for competition in [item for item in metadata["competitions"] if item.get("tenant_id") == normalized_tenant_id]:
        competition_club_ids = [item for item in _competition_club_ids(metadata, str(competition.get("id") or ""), tenant_id=normalized_tenant_id) if item != club_id]
        _set_competition_club_ids(metadata, str(competition.get("id") or ""), competition_club_ids, tenant_id=normalized_tenant_id)
    save_metadata(metadata, tenant_id=tenant_id)


def save_uploaded_logo(data_url: str, folder: str, name_hint: str, tenant_id: Optional[str] = None) -> str:
    if not data_url:
        raise ValueError("Logo data is required.")

    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        raise ValueError("Logo must be a base64 data URL.")

    mime = match.group("mime").lower()
    raw_data = match.group("data")
    extension = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }.get(mime)
    if extension is None:
        raise ValueError("Unsupported image type.")

    try:
        content = base64.b64decode(raw_data)
    except ValueError as exc:
        raise ValueError("Invalid base64 logo data.") from exc

    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    target_dir = ASSETS_DIR / "tenants" / normalized_tenant_id / _slugify(folder)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_slugify(name_hint)}-{uuid4().hex[:8]}{extension}"
    file_path = target_dir / filename
    file_path.write_bytes(content)
    return f"/assets/tenants/{normalized_tenant_id}/{_slugify(folder)}/{filename}"


def save_branding_asset(*, admin_id: str, asset_kind: str, data_url: str) -> str:
    if asset_kind not in {"logo", "icon", "splash"}:
        raise ValueError("Unsupported branding asset type.")
    if not data_url:
        raise ValueError("Branding asset data is required.")
    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        raise ValueError("Branding asset must be a base64 data URL.")
    mime = match.group("mime").lower()
    raw_data = match.group("data")
    extension = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }.get(mime)
    if extension is None:
        raise ValueError("Unsupported image type.")
    try:
        content = base64.b64decode(raw_data)
    except ValueError as exc:
        raise ValueError("Invalid base64 image data.") from exc

    folder = ASSETS_DIR / "branding" / str(admin_id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{asset_kind}{extension}"
    file_path = folder / filename
    file_path.write_bytes(content)
    return f"/assets/branding/{admin_id}/{filename}"


def load_users() -> List[Dict[str, object]]:
    payload = _read_json(USERS_PATH, [])
    if not isinstance(payload, list):
        return []
    users = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        current = dict(item)
        current["tenant_id"] = _normalize_tenant_id(current.get("tenant_id"))
        users.append(current)
    return users


def save_users(users: List[Dict[str, object]]) -> None:
    _write_json(USERS_PATH, users)


def get_user(device_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, object]]:
    normalized_device_id = str(device_id or "").strip()
    if not normalized_device_id:
        return None
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    return next(
        (
            item
            for item in load_users()
            if str(item.get("device_id") or "").strip() == normalized_device_id
            and str(item.get("tenant_id") or DEFAULT_TENANT_ID) == normalized_tenant_id
        ),
        None,
    )


def _base_user_payload(
    *,
    device_id: str,
    device_name: str,
    platform: str,
    app_version: str,
    device_fingerprint: str = "",
    tenant_id: Optional[str] = None,
) -> Dict[str, object]:
    now = utc_now()
    tenant = get_tenant(tenant_id)
    trial_days = int((tenant.get("trial_policy") or {}).get("duration_days") or TRIAL_DAYS)
    trial_end = now + timedelta(days=trial_days)
    return {
        "id": uuid4().hex,
        "tenant_id": tenant["tenant_id"],
        "device_id": device_id,
        "allowed_device": device_id,
        "device_name": device_name,
        "admin_name": "",
        "status": "trial",
        "trial_start": now.isoformat(),
        "trial_end": trial_end.isoformat(),
        "subscription_end": None,
        "free_access": False,
        "last_seen": now.isoformat(),
        "platform": platform,
        "app_version": app_version,
        "device_fingerprint": device_fingerprint,
        "allowed_fingerprint": device_fingerprint,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "blocked_at": None,
        "last_ip": "",
        "last_country": "",
        "ip_history": [],
        "country_history": [],
        "suspicious_activity": False,
        "vpn_detected": False,
        "vpn_policy": "allow",
        "vpn_blocked": False,
        "insecure_device": False,
        "signature_mismatch": False,
        "device_reset_required": False,
    }


def _compute_user_status(user: Dict[str, object]) -> str:
    if bool(user.get("device_reset_required")):
        return "device_blocked"
    if bool(user.get("free_access")):
        return "free"
    if user.get("blocked_at"):
        return "blocked"
    if bool(user.get("insecure_device")) or bool(user.get("signature_mismatch")):
        return "insecure_device"
    if bool(user.get("vpn_detected")) and str(user.get("vpn_policy") or "allow") == "block":
        return "vpn_blocked"

    now = utc_now()
    subscription_end = parse_datetime(str(user.get("subscription_end") or ""))
    if subscription_end and subscription_end >= now:
        return "active"

    trial_end = parse_datetime(str(user.get("trial_end") or ""))
    if trial_end and trial_end >= now:
        return "trial"

    return "expired"


def _decorate_user(user: Dict[str, object], persist: bool = False) -> Dict[str, object]:
    decorated = dict(user)
    decorated["id"] = str(decorated.get("id") or uuid4().hex).strip()
    decorated["tenant_id"] = _normalize_tenant_id(decorated.get("tenant_id"))
    decorated["device_id"] = str(decorated.get("device_id") or "").strip()
    decorated["device_name"] = str(decorated.get("device_name") or "").strip() or "Unknown Device"
    decorated["admin_name"] = str(decorated.get("admin_name") or "").strip()
    decorated["platform"] = str(decorated.get("platform") or "").strip()
    decorated["app_version"] = str(decorated.get("app_version") or "").strip()
    decorated["free_access"] = bool(decorated.get("free_access"))
    decorated["allowed_device"] = str(decorated.get("allowed_device") or decorated["device_id"]).strip()
    decorated["device_fingerprint"] = str(decorated.get("device_fingerprint") or "").strip()
    decorated["allowed_fingerprint"] = str(decorated.get("allowed_fingerprint") or "").strip()
    decorated["last_ip"] = str(decorated.get("last_ip") or "").strip()
    decorated["last_country"] = str(decorated.get("last_country") or "").strip()
    decorated["suspicious_activity"] = bool(decorated.get("suspicious_activity"))
    decorated["vpn_detected"] = bool(decorated.get("vpn_detected"))
    decorated["vpn_policy"] = str(decorated.get("vpn_policy") or "allow")
    decorated["vpn_blocked"] = bool(decorated.get("vpn_blocked"))
    decorated["insecure_device"] = bool(decorated.get("insecure_device"))
    decorated["signature_mismatch"] = bool(decorated.get("signature_mismatch"))
    decorated["device_reset_required"] = bool(decorated.get("device_reset_required"))
    if not isinstance(decorated.get("ip_history"), list):
        decorated["ip_history"] = []
    if not isinstance(decorated.get("country_history"), list):
        decorated["country_history"] = []
    decorated["status"] = _compute_user_status(decorated)
    decorated["display_name"] = decorated["admin_name"] or decorated["device_name"]
    decorated["username"] = decorated["display_name"]
    decorated["expiry_date"] = str(decorated.get("subscription_end") or decorated.get("trial_end") or "").strip()
    decorated["is_allowed"] = decorated["status"] in {"trial", "active", "free"}
    decorated["updated_at"] = str(decorated.get("updated_at") or utc_now_iso())
    if persist:
        decorated["updated_at"] = utc_now_iso()
    return decorated


def _replace_user(users: List[Dict[str, object]], payload: Dict[str, object]) -> List[Dict[str, object]]:
    device_id = str(payload.get("device_id") or "").strip()
    tenant_id = _normalize_tenant_id(payload.get("tenant_id"))
    replaced = False
    next_users: List[Dict[str, object]] = []
    for user in users:
        if str(user.get("device_id") or "").strip() == device_id and _normalize_tenant_id(user.get("tenant_id")) == tenant_id:
            next_users.append(payload)
            replaced = True
        else:
            next_users.append(user)
    if not replaced:
        next_users.append(payload)
    return sorted(next_users, key=lambda item: str(item.get("created_at") or ""))


def _append_limited_history(values: List[str], value: str, limit: int = 6) -> List[str]:
    next_values = [str(item).strip() for item in values if str(item).strip()]
    normalized = str(value or "").strip()
    if normalized:
        next_values.append(normalized)
    return next_values[-limit:]


def _infer_country(ip_address: str, country: str) -> str:
    normalized_country = _normalize_name(country or "")
    if normalized_country:
        return normalized_country
    ip_value = str(ip_address or "").strip()
    if not ip_value:
        return ""
    if ip_value.startswith(PRIVATE_IP_PREFIXES):
        return "Local Network"
    return "Unknown"


def _is_public_ip(ip_address: str) -> bool:
    value = str(ip_address or "").strip()
    if not value:
        return False
    return not value.startswith(PRIVATE_IP_PREFIXES)


def _record_security_issue(user: Dict[str, object], issue: str, detail: str) -> None:
    log_security_event(
        device_id=str(user.get("device_id") or ""),
        issue=issue,
        detail=detail,
    )


def _update_user_security_state(
    user: Dict[str, object],
    *,
    ip_address: str = "",
    country: str = "",
    device_fingerprint: str = "",
    vpn_active: bool = False,
    secure_device: bool = True,
    app_signature_valid: bool = True,
) -> None:
    normalized_ip = str(ip_address or "").strip()
    normalized_fingerprint = str(device_fingerprint or "").strip()
    resolved_country = _infer_country(normalized_ip, country)

    previous_ip = str(user.get("last_ip") or "").strip()
    previous_country = str(user.get("last_country") or "").strip()
    user["last_ip"] = normalized_ip
    user["last_country"] = resolved_country
    user["ip_history"] = _append_limited_history(list(user.get("ip_history") or []), normalized_ip)
    user["country_history"] = _append_limited_history(list(user.get("country_history") or []), resolved_country)
    user["device_fingerprint"] = normalized_fingerprint or str(user.get("device_fingerprint") or "")
    user["vpn_detected"] = bool(vpn_active)
    user["vpn_blocked"] = bool(vpn_active) and str(user.get("vpn_policy") or "allow") == "block"
    user["insecure_device"] = not bool(secure_device)
    user["signature_mismatch"] = not bool(app_signature_valid)

    allowed_fingerprint = str(user.get("allowed_fingerprint") or "").strip()
    if bool(user.get("device_reset_required")):
        if normalized_fingerprint and normalized_fingerprint == allowed_fingerprint:
            user["device_reset_required"] = False
        else:
            user["suspicious_activity"] = True
    elif allowed_fingerprint and normalized_fingerprint and allowed_fingerprint != normalized_fingerprint:
        user["device_reset_required"] = True
        user["suspicious_activity"] = True
        _record_security_issue(user, "device_mismatch", "A different device fingerprint attempted to use the locked subscription.")
    elif not allowed_fingerprint and normalized_fingerprint:
        user["allowed_fingerprint"] = normalized_fingerprint

    if previous_country and resolved_country and previous_country != resolved_country and previous_country != "Unknown":
        user["suspicious_activity"] = True
        _record_security_issue(user, "country_switch", f"{previous_country} -> {resolved_country}")

    distinct_public_ips = {
        item for item in list(user.get("ip_history") or []) if _is_public_ip(str(item))
    }
    if len(distinct_public_ips) >= 3:
        user["suspicious_activity"] = True
        _record_security_issue(user, "ip_switching", f"Observed {len(distinct_public_ips)} public IP addresses.")

    if previous_ip and normalized_ip and previous_ip != normalized_ip and _is_public_ip(previous_ip) and _is_public_ip(normalized_ip):
        user["suspicious_activity"] = True

    if user["vpn_detected"]:
        _record_security_issue(user, "vpn_detected", "VPN or proxy usage detected.")
    if user["insecure_device"]:
        _record_security_issue(user, "insecure_device", "Rooted or jailbroken device detected.")
    if user["signature_mismatch"]:
        _record_security_issue(user, "signature_mismatch", "App signature verification failed.")


def register_device(
    *,
    device_id: str,
    device_name: str,
    platform: str,
    app_version: str,
    device_fingerprint: str = "",
    tenant_id: Optional[str] = None,
    ip_address: str = "",
    country: str = "",
    vpn_active: bool = False,
    secure_device: bool = True,
    app_signature_valid: bool = True,
) -> Dict[str, object]:
    normalized_device_id = str(device_id or "").strip()
    normalized_name = _normalize_name(device_name or "")
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    if not normalized_device_id:
        raise ValueError("device_id is required.")
    if not normalized_name:
        raise ValueError("device_name is required.")

    users = load_users()
    existing = next(
        (
            item
            for item in users
            if str(item.get("device_id") or "").strip() == normalized_device_id
            and _normalize_tenant_id(item.get("tenant_id")) == normalized_tenant_id
        ),
        None,
    )

    now_iso = utc_now_iso()
    if existing is None:
        payload = _base_user_payload(
            device_id=normalized_device_id,
            device_name=normalized_name,
            platform=str(platform or "").strip(),
            app_version=str(app_version or "").strip(),
            device_fingerprint=str(device_fingerprint or "").strip(),
            tenant_id=normalized_tenant_id,
        )
    else:
        payload = _decorate_user(existing, persist=False)
        payload["device_name"] = normalized_name
        payload["platform"] = str(platform or "").strip()
        payload["app_version"] = str(app_version or "").strip()
        payload["last_seen"] = now_iso
        payload["updated_at"] = now_iso

    _update_user_security_state(
        payload,
        ip_address=ip_address,
        country=country,
        device_fingerprint=str(device_fingerprint or "").strip(),
        vpn_active=vpn_active,
        secure_device=secure_device,
        app_signature_valid=app_signature_valid,
    )
    payload = _decorate_user(payload, persist=False)
    payload["last_seen"] = now_iso
    users = _replace_user(users, payload)
    save_users(users)
    return payload


def get_device_status(
    device_id: str,
    touch: bool = True,
    *,
    tenant_id: Optional[str] = None,
    ip_address: str = "",
    country: str = "",
    device_fingerprint: str = "",
    vpn_active: bool = False,
    secure_device: bool = True,
    app_signature_valid: bool = True,
) -> Dict[str, object]:
    user = get_user(device_id, tenant_id=tenant_id)
    if user is None:
        raise ValueError("Device not registered.")

    decorated = _decorate_user(user, persist=False)
    _update_user_security_state(
        decorated,
        ip_address=ip_address,
        country=country,
        device_fingerprint=str(device_fingerprint or "").strip(),
        vpn_active=vpn_active,
        secure_device=secure_device,
        app_signature_valid=app_signature_valid,
    )
    if touch:
        decorated["last_seen"] = utc_now_iso()
        decorated["updated_at"] = decorated["last_seen"]
        users = _replace_user(load_users(), decorated)
        save_users(users)

    return {
        **decorated,
        "message": _status_message(decorated["status"]),
    }


def _status_message(status: str) -> str:
    if status == "device_blocked":
        return "This subscription is locked to another device."
    if status == "insecure_device":
        return "Playback is blocked on insecure or modified devices."
    if status == "vpn_blocked":
        return "VPN usage is blocked for this device."
    if status == "trial":
        return "Trial active."
    if status == "active":
        return "Subscription active."
    if status == "free":
        return "Free access granted."
    if status == "blocked":
        return "Access disabled by admin."
    return "Trial expired. Subscription required."


def list_users(tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    users = [_decorate_user(item, persist=False) for item in load_users() if _normalize_tenant_id(item.get("tenant_id")) == normalized_tenant_id]
    users.sort(
        key=lambda item: (
            str(item.get("status") or ""),
            str(item.get("display_name") or "").lower(),
            str(item.get("device_id") or ""),
        )
    )
    return users


def list_online_users(tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    threshold = utc_now() - timedelta(minutes=ONLINE_WINDOW_MINUTES)
    return [
        user
        for user in list_users(tenant_id=tenant_id)
        if (parse_datetime(str(user.get("last_seen") or "")) or datetime.min.replace(tzinfo=UTC))
        >= threshold
    ]


def get_user_stats(tenant_id: Optional[str] = None) -> Dict[str, int]:
    users = list_users(tenant_id=tenant_id)
    return {
        "total_users": len(users),
        "trial_users": sum(1 for item in users if item.get("status") == "trial"),
        "active_users": sum(1 for item in users if item.get("status") == "active"),
        "blocked_users": sum(1 for item in users if item.get("status") in {"blocked", "device_blocked", "insecure_device", "vpn_blocked"}),
        "live_viewers": len(list_online_users(tenant_id=tenant_id)),
    }


def _update_user(device_id: str, updater, tenant_id: Optional[str] = None) -> Dict[str, object]:
    users = load_users()
    user = next(
        (
            item
            for item in users
            if str(item.get("device_id") or "").strip() == str(device_id).strip()
            and _normalize_tenant_id(item.get("tenant_id")) == _normalize_tenant_id(tenant_id)
        ),
        None,
    )
    if user is None:
        raise ValueError("User not found.")
    payload = _decorate_user(user, persist=False)
    updater(payload)
    payload["updated_at"] = utc_now_iso()
    payload = _decorate_user(payload, persist=False)
    save_users(_replace_user(users, payload))
    return payload


def block_user(device_id: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    return _update_user(device_id, lambda user: user.update({"blocked_at": utc_now_iso()}), tenant_id=tenant_id)


def unblock_user(device_id: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    return _update_user(device_id, lambda user: user.update({"blocked_at": None}), tenant_id=tenant_id)


def grant_free_access(device_id: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    return _update_user(device_id, lambda user: user.update({"free_access": True, "blocked_at": None}), tenant_id=tenant_id)


def remove_free_access(device_id: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    return _update_user(device_id, lambda user: user.update({"free_access": False}), tenant_id=tenant_id)


def extend_subscription(device_id: str, plan: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    normalized_plan = str(plan or "").strip().lower()
    tenant = get_tenant(tenant_id)
    plan_days = next(
        (
            int(item.get("duration_days") or 0)
            for item in list(tenant.get("subscription_plans") or [])
            if str(item.get("id") or "").strip().lower() == normalized_plan
        ),
        0,
    )
    delta = timedelta(days=plan_days) if plan_days > 0 else _SUBSCRIPTION_PLAN_DELTAS.get(normalized_plan)
    if delta is None:
        raise ValueError("Plan must be '6_months' or '1_year'.")

    def updater(user: Dict[str, object]) -> None:
        current_end = parse_datetime(str(user.get("subscription_end") or ""))
        now = utc_now()
        base = current_end if current_end and current_end > now else now
        user["subscription_end"] = (base + delta).isoformat()
        user["blocked_at"] = None

    return _update_user(device_id, updater, tenant_id=tenant_id)


def extend_user_expiry_days(device_id: str, days: int, tenant_id: Optional[str] = None) -> Dict[str, object]:
    extra_days = int(days or 0)
    if extra_days <= 0:
        raise ValueError("days must be greater than 0.")

    def updater(user: Dict[str, object]) -> None:
        current_end = parse_datetime(str(user.get("subscription_end") or user.get("trial_end") or ""))
        now = utc_now()
        base = current_end if current_end and current_end > now else now
        user["subscription_end"] = (base + timedelta(days=extra_days)).isoformat()
        user["blocked_at"] = None

    return _update_user(device_id, updater, tenant_id=tenant_id)


def rename_user(device_id: str, admin_name: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    normalized_name = _normalize_name(admin_name or "")
    if not normalized_name:
        raise ValueError("admin_name is required.")
    return _update_user(device_id, lambda user: user.update({"admin_name": normalized_name}), tenant_id=tenant_id)


def restore_user_name(device_id: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    return _update_user(device_id, lambda user: user.update({"admin_name": ""}), tenant_id=tenant_id)


def reset_user_device(device_id: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    def updater(user: Dict[str, object]) -> None:
        user["allowed_fingerprint"] = ""
        user["device_reset_required"] = False
        user["suspicious_activity"] = False
    return _update_user(device_id, updater, tenant_id=tenant_id)


def set_user_vpn_policy(device_id: str, policy: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    normalized = str(policy or "").strip().lower()
    if normalized not in {"allow", "block"}:
        raise ValueError("VPN policy must be 'allow' or 'block'.")
    return _update_user(device_id, lambda user: user.update({"vpn_policy": normalized, "vpn_blocked": bool(user.get("vpn_detected")) and normalized == "block"}), tenant_id=tenant_id)


def load_viewer_sessions(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    path = _tenant_file_path(resolved_admin_id, "analytics.json") if resolved_admin_id else VIEWERS_PATH
    payload = _read_json(path, [])
    if not isinstance(payload, list):
        return []
    return [{**item, "tenant_id": _normalize_tenant_id(item.get("tenant_id"))} for item in payload if isinstance(item, dict)]


def save_viewer_sessions(sessions: List[Dict[str, object]], *, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> None:
    trimmed = sessions[-MAX_VIEWER_SESSIONS:]
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    path = _tenant_file_path(resolved_admin_id, "analytics.json") if resolved_admin_id else VIEWERS_PATH
    _write_json(path, trimmed)


def _active_viewer_key(device_id: str, stream_id: str, tenant_id: Optional[str] = None) -> str:
    return f"{_normalize_tenant_id(tenant_id)}::{str(device_id).strip()}::{str(stream_id).strip()}"


def _normalize_timestamp(value: Optional[str]) -> str:
    parsed = parse_datetime(value)
    return (parsed or utc_now()).isoformat()


def _session_match_label(session: Dict[str, object]) -> str:
    home = str(session.get("home_club") or "").strip()
    away = str(session.get("away_club") or "").strip()
    if home and away:
        return f"{home} vs {away}"
    return str(session.get("match") or session.get("stream_id") or "Unknown Match")


def start_viewer_session(
    *,
    tenant_id: Optional[str] = None,
    device_id: str,
    stream_id: str,
    competition: str,
    home_club: str,
    away_club: str,
    timestamp: Optional[str] = None,
    country: Optional[str] = None,
) -> Dict[str, object]:
    normalized_device_id = str(device_id or "").strip()
    normalized_stream_id = str(stream_id or "").strip()
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    if not normalized_device_id:
        raise ValueError("device_id is required.")
    if not normalized_stream_id:
        raise ValueError("stream_id is required.")
    if get_user(normalized_device_id, tenant_id=normalized_tenant_id) is None:
        raise ValueError("Device not registered.")

    start_time = _normalize_timestamp(timestamp)
    session = {
        "tenant_id": normalized_tenant_id,
        "device_id": normalized_device_id,
        "stream_id": normalized_stream_id,
        "competition": _normalize_name(competition or ""),
        "home_club": _normalize_name(home_club or ""),
        "away_club": _normalize_name(away_club or ""),
        "start_time": start_time,
        "stop_time": None,
        "duration": 0,
        "country": _normalize_name(country or ""),
    }
    session["match"] = _session_match_label(session)
    _ACTIVE_VIEWERS[_active_viewer_key(normalized_device_id, normalized_stream_id, normalized_tenant_id)] = session
    return dict(session)


def stop_viewer_session(
    *,
    tenant_id: Optional[str] = None,
    device_id: str,
    stream_id: str,
    timestamp: Optional[str] = None,
) -> Dict[str, object]:
    normalized_device_id = str(device_id or "").strip()
    normalized_stream_id = str(stream_id or "").strip()
    key = _active_viewer_key(normalized_device_id, normalized_stream_id, tenant_id)
    session = _ACTIVE_VIEWERS.pop(key, None)
    if session is None:
        raise ValueError("Active viewer session not found.")
    if _normalize_tenant_id(session.get("tenant_id")) != _normalize_tenant_id(tenant_id):
        raise ValueError("Active viewer session not found.")

    stop_time = _normalize_timestamp(timestamp)
    start_time = parse_datetime(str(session.get("start_time") or "")) or utc_now()
    stop_dt = parse_datetime(stop_time) or utc_now()
    duration = max(int((stop_dt - start_time).total_seconds()), 0)

    completed = {
        **session,
        "stop_time": stop_time,
        "duration": duration,
        "match": _session_match_label(session),
    }
    sessions = load_viewer_sessions(tenant_id=tenant_id)
    sessions.append(completed)
    save_viewer_sessions(sessions, tenant_id=tenant_id)
    return completed


def get_live_analytics(tenant_id: Optional[str] = None) -> Dict[str, object]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    sessions = [item for item in _ACTIVE_VIEWERS.values() if _normalize_tenant_id(item.get("tenant_id")) == normalized_tenant_id]
    stream_counts: Dict[str, Dict[str, object]] = {}
    competition_counts: Dict[str, int] = {}
    for session in sessions:
        stream_id = str(session.get("stream_id") or "")
        entry = stream_counts.setdefault(
            stream_id,
            {
                "stream_id": stream_id,
                "match": _session_match_label(session),
                "competition": str(session.get("competition") or ""),
                "viewers": 0,
                "current_viewers": 0,
            },
        )
        entry["viewers"] = int(entry["viewers"]) + 1
        entry["current_viewers"] = int(entry["current_viewers"]) + 1
        competition = str(session.get("competition") or "").strip()
        if competition:
            competition_counts[competition] = competition_counts.get(competition, 0) + 1

    streams = sorted(stream_counts.values(), key=lambda item: int(item["viewers"]), reverse=True)
    competitions = [
        {"competition": name, "viewers": viewers}
        for name, viewers in sorted(competition_counts.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "live_viewers": len(sessions),
        "streams": streams,
        "competitions": competitions,
    }


def get_stream_live_analytics(tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    return list(get_live_analytics(tenant_id=tenant_id)["streams"])


def _today_prefix() -> str:
    return utc_now().date().isoformat()


def get_top_matches(limit: int = 10, today_only: bool = True, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    counts: Dict[str, Dict[str, object]] = {}
    today = _today_prefix()
    for session in load_viewer_sessions(tenant_id=tenant_id):
        if _normalize_tenant_id(session.get("tenant_id")) != _normalize_tenant_id(tenant_id):
            continue
        start_time = str(session.get("start_time") or "")
        if today_only and not start_time.startswith(today):
            continue
        label = _session_match_label(session)
        entry = counts.setdefault(
            label,
            {
                "match": label,
                "competition": str(session.get("competition") or ""),
                "viewers": 0,
                "unique_devices": set(),
            },
        )
        entry["viewers"] = int(entry["viewers"]) + 1
        entry["unique_devices"].add(str(session.get("device_id") or ""))

    results = []
    for entry in counts.values():
        results.append(
            {
                "match": entry["match"],
                "competition": entry["competition"],
                "viewers": entry["viewers"],
                "unique_devices": len(entry["unique_devices"]),
            }
        )
    results.sort(key=lambda item: int(item["viewers"]), reverse=True)
    return results[:limit]


def get_top_competitions(limit: int = 10, today_only: bool = True, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    counts: Dict[str, Dict[str, object]] = {}
    today = _today_prefix()
    for session in load_viewer_sessions(tenant_id=tenant_id):
        if _normalize_tenant_id(session.get("tenant_id")) != _normalize_tenant_id(tenant_id):
            continue
        start_time = str(session.get("start_time") or "")
        if today_only and not start_time.startswith(today):
            continue
        competition = str(session.get("competition") or "").strip() or "Unknown Competition"
        entry = counts.setdefault(competition, {"competition": competition, "viewers": 0, "watch_time": 0})
        entry["viewers"] = int(entry["viewers"]) + 1
        entry["watch_time"] = int(entry["watch_time"]) + int(session.get("duration") or 0)
    results = list(counts.values())
    results.sort(key=lambda item: int(item["viewers"]), reverse=True)
    return results[:limit]


def get_daily_viewers(days: int = 14, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    counts: Dict[str, Dict[str, object]] = {}
    for session in load_viewer_sessions(tenant_id=tenant_id):
        if _normalize_tenant_id(session.get("tenant_id")) != _normalize_tenant_id(tenant_id):
            continue
        start_time = str(session.get("start_time") or "")
        date_key = start_time[:10]
        if not date_key:
            continue
        entry = counts.setdefault(date_key, {"date": date_key, "viewer_sessions": 0, "watch_time": 0})
        entry["viewer_sessions"] = int(entry["viewer_sessions"]) + 1
        entry["watch_time"] = int(entry["watch_time"]) + int(session.get("duration") or 0)
    results = sorted(counts.values(), key=lambda item: item["date"])
    return results[-days:]


def get_country_viewers(limit: int = 20, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    counts: Dict[str, int] = {}
    for session in load_viewer_sessions(tenant_id=tenant_id):
        if _normalize_tenant_id(session.get("tenant_id")) != _normalize_tenant_id(tenant_id):
            continue
        country = str(session.get("country") or "").strip()
        if not country:
            continue
        counts[country] = counts.get(country, 0) + 1
    results = [{"country": name, "viewers": viewers} for name, viewers in counts.items()]
    results.sort(key=lambda item: int(item["viewers"]), reverse=True)
    return results[:limit]


def load_stream_sessions() -> List[Dict[str, object]]:
    payload = _read_json(SESSIONS_PATH, [])
    if not isinstance(payload, list):
        return []
    return [{**item, "tenant_id": _normalize_tenant_id(item.get("tenant_id"))} for item in payload if isinstance(item, dict)]


def save_stream_sessions(sessions: List[Dict[str, object]]) -> None:
    _write_json(SESSIONS_PATH, sessions[-MAX_STREAM_SESSIONS:])


def load_security_logs() -> List[Dict[str, object]]:
    payload = _read_json(SECURITY_LOGS_PATH, [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def save_security_logs(logs: List[Dict[str, object]]) -> None:
    _write_json(SECURITY_LOGS_PATH, logs[-MAX_SECURITY_LOGS:])


def log_security_event(*, device_id: str, issue: str, detail: str) -> Dict[str, object]:
    user = next((item for item in load_users() if str(item.get("device_id") or "").strip() == str(device_id or "").strip()), None)
    entry = {
        "id": uuid4().hex,
        "device_id": str(device_id or "").strip(),
        "tenant_id": _normalize_tenant_id(user.get("tenant_id") if user else DEFAULT_TENANT_ID),
        "issue": str(issue or "").strip(),
        "detail": str(detail or "").strip(),
        "timestamp": utc_now_iso(),
    }
    logs = load_security_logs()
    logs.append(entry)
    save_security_logs(logs)
    return entry


def _token_secret() -> bytes:
    return (os.getenv("STREAM_TOKEN_SECRET") or "local-stream-token-secret").encode("utf-8")


def _tenant_auth_secret() -> bytes:
    return (os.getenv("TENANT_AUTH_SECRET") or "local-tenant-auth-secret").encode("utf-8")


def _license_secret() -> bytes:
    return (os.getenv("LICENSE_TOKEN_SECRET") or "local-license-token-secret").encode("utf-8")


def _sign_payload(payload: str) -> str:
    return hmac.new(_token_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _sign_tenant_payload(payload: str) -> str:
    return hmac.new(_tenant_auth_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _sign_license_payload(payload: str) -> str:
    return hmac.new(_license_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _encode_token(payload: Dict[str, object]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = _sign_payload(body)
    token_body = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{token_body}.{signature}"


def _encode_license_token(payload: Dict[str, object]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = _sign_license_payload(body)
    token_body = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{token_body}.{signature}"


def create_tenant_access_token(tenant_id: str, username: str) -> Dict[str, object]:
    now = utc_now()
    payload = {
        "tenant_id": _normalize_tenant_id(tenant_id),
        "username": str(username or "").strip(),
        "exp": int((now + timedelta(hours=12)).timestamp()),
        "nonce": secrets.token_hex(8),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = _sign_tenant_payload(body)
    token_body = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    return {"token": f"{token_body}.{signature}", "expires_at": (now + timedelta(hours=12)).isoformat()}


def validate_tenant_access_token(token: str) -> Dict[str, object]:
    try:
        token_body, signature = token.split(".", 1)
        padded = token_body + "=" * ((4 - len(token_body) % 4) % 4)
        body = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise ValueError("Invalid tenant access token.") from exc
    expected = _sign_tenant_payload(body)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid tenant access token signature.")
    payload = json.loads(body)
    if int(payload.get("exp") or 0) < int(utc_now().timestamp()):
        raise ValueError("Tenant access token expired.")
    get_tenant(payload.get("tenant_id"))
    return payload


def _decode_license_token(token: str) -> Dict[str, object]:
    try:
        token_body, signature = token.split(".", 1)
        padded = token_body + "=" * ((4 - len(token_body) % 4) % 4)
        body = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise ValueError("Invalid license token.") from exc
    expected = _sign_license_payload(body)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid license token signature.")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Invalid license token payload.")
    return payload


def get_admin_license(admin_id: str) -> Optional[Dict[str, object]]:
    licenses = [item for item in load_licenses() if str(item.get("admin_id") or "") == str(admin_id or "")]
    if not licenses:
        return None
    licenses.sort(key=lambda item: str(item.get("issued_at") or ""), reverse=True)
    return licenses[0]


def generate_license_for_admin(*, admin_id: str, activation_limit: int = 1) -> Dict[str, object]:
    admin = get_admin_by_id(admin_id)
    if admin is None:
        raise ValueError("Admin not found.")
    existing = get_admin_license(admin_id)
    if existing is not None:
        return existing
    license_item = _decorate_license(
        {
            "license_key": f"LIC-{uuid4().hex.upper()}",
            "admin_id": str(admin_id),
            "tenant_id": str(admin.get("tenant_id") or ""),
            "server_ip": str(admin.get("server_ip") or ""),
            "device_id": "",
            "status": "inactive",
            "issued_at": utc_now_iso(),
            "activated_at": "",
            "expires_at": str(admin.get("subscription_end_date") or admin.get("subscription_end") or ""),
            "activation_count": 0,
            "activation_limit": max(1, int(activation_limit or 1)),
            "subscription_plan": str(admin.get("plan_id") or "trial"),
            "app_version": "",
        }
    )
    items = load_licenses()
    items.append(license_item)
    save_licenses(items)
    update_tenant_record(
        str(admin.get("tenant_id") or ""),
        {
            "license_key": license_item["license_key"],
            "subscription_plan": str(admin.get("plan_id") or "trial"),
            "server_ip": str(admin.get("server_ip") or ""),
            "email": str(admin.get("email") or ""),
            "status": str(admin.get("status") or _default_tenant_status()),
        },
    )
    return license_item


def activate_license_key(*, license_key: str, device_id: str, app_version: str) -> Dict[str, object]:
    normalized_key = str(license_key or "").strip().upper()
    normalized_device_id = str(device_id or "").strip()
    if not normalized_key or not normalized_device_id:
        raise ValueError("license_key and device_id are required.")
    licenses = load_licenses()
    license_item = next((item for item in licenses if str(item.get("license_key") or "").upper() == normalized_key), None)
    if license_item is None:
        raise ValueError("License key not found.")
    admin = get_admin_by_id(str(license_item.get("admin_id") or ""))
    if admin is None:
        raise ValueError("License owner not found.")
    if str(admin.get("subscription_status") or "") == "expired":
        license_item["status"] = "expired"
        save_licenses(licenses)
        raise ValueError("Subscription expired.")
    if license_item.get("device_id") and str(license_item.get("device_id")) != normalized_device_id:
        if str(admin.get("role") or "").strip().lower() != "master":
            raise ValueError("License is already activated on another device.")
    if int(license_item.get("activation_count") or 0) >= int(license_item.get("activation_limit") or 1) and not license_item.get("device_id"):
        raise ValueError("License activation limit reached.")
    license_item["device_id"] = normalized_device_id
    license_item["status"] = "active" if str(admin.get("subscription_status") or "") != "trial" else "active"
    license_item["activated_at"] = str(license_item.get("activated_at") or utc_now_iso())
    license_item["activation_count"] = max(int(license_item.get("activation_count") or 0), 1)
    license_item["expires_at"] = str(admin.get("subscription_end_date") or admin.get("subscription_end") or license_item.get("expires_at") or "")
    license_item["subscription_plan"] = str(admin.get("plan_id") or license_item.get("subscription_plan") or "trial")
    license_item["app_version"] = str(app_version or "").strip()
    save_licenses(licenses)
    token = _encode_license_token(
        {
            "license_key": license_item["license_key"],
            "admin_id": license_item["admin_id"],
            "device_id": license_item["device_id"],
            "status": license_item["status"],
            "expires_at": license_item["expires_at"],
            "subscription_plan": license_item["subscription_plan"],
            "app_version": license_item["app_version"],
            "nonce": secrets.token_hex(12),
        }
    )
    return {
        "license": license_item,
        "license_token": token,
        "valid": True,
        "verification_key": "embedded-license-verification-v1",
    }


def validate_license_token_payload(*, license_token: str, device_id: str) -> Dict[str, object]:
    payload = _decode_license_token(license_token)
    normalized_device_id = str(device_id or "").strip()
    if str(payload.get("device_id") or "") != normalized_device_id:
        raise ValueError("License device mismatch.")
    licenses = load_licenses()
    license_item = next((item for item in licenses if str(item.get("license_key") or "") == str(payload.get("license_key") or "")), None)
    if license_item is None:
        raise ValueError("License record not found.")
    admin = get_admin_by_id(str(license_item.get("admin_id") or ""))
    if admin is None:
        raise ValueError("License owner not found.")
    expires_at = parse_datetime(str(license_item.get("expires_at") or payload.get("expires_at") or ""))
    if expires_at and expires_at < utc_now():
        license_item["status"] = "expired"
        save_licenses(licenses)
        raise ValueError("License expired.")
    if str(license_item.get("status") or "") not in {"active"}:
        raise ValueError("License inactive.")
    if license_item.get("device_id") and str(license_item.get("device_id")) != normalized_device_id:
        raise ValueError("License bound to another device.")
    if str(admin.get("subscription_status") or "") == "expired":
        raise ValueError("Subscription expired.")
    license_item["last_validated_at"] = utc_now_iso()
    save_licenses(licenses)
    return {
        "valid": True,
        "license": license_item,
        "admin_id": admin.get("admin_id"),
        "subscription_plan": license_item.get("subscription_plan"),
        "expires_at": license_item.get("expires_at"),
    }


def revoke_license(*, admin_id: str, license_key: str) -> Dict[str, object]:
    licenses = load_licenses()
    license_item = next((item for item in licenses if str(item.get("license_key") or "") == str(license_key or "")), None)
    if license_item is None:
        raise ValueError("License not found.")
    if str(license_item.get("admin_id") or "") != str(admin_id or ""):
        raise ValueError("License does not belong to this admin.")
    license_item["status"] = "inactive"
    save_licenses(licenses)
    return license_item


def reassign_license(*, admin_id: str, license_key: str) -> Dict[str, object]:
    licenses = load_licenses()
    license_item = next((item for item in licenses if str(item.get("license_key") or "") == str(license_key or "")), None)
    if license_item is None:
        raise ValueError("License not found.")
    if str(license_item.get("admin_id") or "") != str(admin_id or ""):
        raise ValueError("License does not belong to this admin.")
    license_item["device_id"] = ""
    license_item["status"] = "inactive"
    license_item["activated_at"] = ""
    license_item["activation_count"] = 0
    save_licenses(licenses)
    return license_item


def _decode_token(token: str) -> Dict[str, object]:
    try:
        token_body, signature = token.split(".", 1)
        padded = token_body + "=" * ((4 - len(token_body) % 4) % 4)
        body = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise ValueError("Invalid stream token.") from exc
    expected = _sign_payload(body)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid stream token signature.")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Invalid stream token payload.")
    return payload


def create_stream_token(*, device_id: str, stream_id: str, tenant_id: Optional[str] = None) -> Dict[str, object]:
    user = get_user(device_id, tenant_id=tenant_id)
    tenant_id = _normalize_tenant_id((user or {}).get("tenant_id") if user else tenant_id)
    status = get_device_status(device_id=device_id, touch=True, tenant_id=tenant_id)
    if not status.get("is_allowed"):
        raise ValueError(str(status.get("message") or "Access denied."))

    now = utc_now()
    sessions = load_stream_sessions()
    next_sessions: List[Dict[str, object]] = []
    for session in sessions:
        if (
            str(session.get("device_id") or "") == str(device_id)
            and _normalize_tenant_id(session.get("tenant_id")) == tenant_id
            and str(session.get("status") or "") == "active"
        ):
            session = {**session, "status": "terminated", "terminated_at": now.isoformat()}
            log_security_event(
                device_id=device_id,
                issue="concurrent_stream_replaced",
                detail=f"Older session for stream {session.get('stream_id')} was terminated by a newer request.",
            )
        next_sessions.append(session)

    session_id = uuid4().hex
    session = {
        "session_id": session_id,
        "tenant_id": tenant_id,
        "device_id": str(device_id),
        "stream_id": str(stream_id),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=STREAM_TOKEN_TTL_SECONDS)).isoformat(),
        "status": "active",
    }
    next_sessions.append(session)
    save_stream_sessions(next_sessions)
    token = _encode_token(
        {
            "device_id": str(device_id),
            "tenant_id": tenant_id,
            "stream_id": str(stream_id),
            "session_id": session_id,
            "exp": int((now + timedelta(seconds=STREAM_TOKEN_TTL_SECONDS)).timestamp()),
            "nonce": secrets.token_hex(8),
        }
    )
    return {"token": token, "session": session}


def validate_stream_token(token: str, *, device_id: Optional[str] = None) -> Dict[str, object]:
    payload = _decode_token(token)
    expires_at = int(payload.get("exp") or 0)
    if expires_at < int(utc_now().timestamp()):
        raise ValueError("Stream token expired.")
    if device_id and str(payload.get("device_id") or "") != str(device_id):
        raise ValueError("Device mismatch.")

    sessions = load_stream_sessions()
    session = next(
        (
            item
            for item in sessions
            if str(item.get("session_id") or "") == str(payload.get("session_id") or "")
        ),
        None,
    )
    if session is None or str(session.get("status") or "") != "active":
        raise ValueError("Stream session is no longer active.")
    if _normalize_tenant_id(session.get("tenant_id")) != _normalize_tenant_id(payload.get("tenant_id")):
        raise ValueError("Stream session tenant mismatch.")

    status = get_device_status(
        device_id=str(payload.get("device_id") or ""),
        touch=True,
        tenant_id=_normalize_tenant_id(payload.get("tenant_id")),
    )
    if not status.get("is_allowed"):
        raise ValueError(str(status.get("message") or "Access denied."))
    return payload


def resolve_playback_url(streams: List[Dict[str, str]], stream_id: str) -> str:
    stream = next((item for item in streams if str(item.get("id") or "") == str(stream_id)), None)
    if stream is None:
        raise ValueError("Stream not found.")
    stream_url = str(stream.get("url") or "").strip()
    if not stream_url:
        raise ValueError("Stream URL unavailable.")
    return stream_url


def get_security_dashboard(tenant_id: Optional[str] = None) -> Dict[str, object]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    users = list_users(tenant_id=normalized_tenant_id)
    flagged_devices = [
        user
        for user in users
        if user.get("suspicious_activity")
        or user.get("vpn_detected")
        or user.get("insecure_device")
        or user.get("device_reset_required")
    ]
    vpn_users = [user for user in users if user.get("vpn_detected")]
    suspicious_ip_changes = [user for user in users if user.get("suspicious_activity")]
    blocked_devices = [
        user
        for user in users
        if user.get("status") in {"blocked", "device_blocked", "insecure_device", "vpn_blocked"}
    ]
    return {
        "flagged_devices": flagged_devices,
        "vpn_users": vpn_users,
        "suspicious_ip_changes": suspicious_ip_changes,
        "blocked_devices": blocked_devices,
        "active_sessions": [item for item in load_stream_sessions() if str(item.get("status") or "") == "active" and _normalize_tenant_id(item.get("tenant_id")) == normalized_tenant_id],
        "security_logs": [item for item in load_security_logs() if _normalize_tenant_id(item.get("tenant_id")) == normalized_tenant_id][-50:],
    }


def _normalize_approved_stream_record(item: Dict[str, object]) -> Optional[Dict[str, object]]:
    stream_id = str(item.get("stream_id") or "").strip()
    if not stream_id:
        return None
    return dict(item)


def load_approved_streams(*, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    path = _tenant_file_path(resolved_admin_id, "approved_streams.json") if resolved_admin_id else APPROVED_STREAMS_PATH
    payload = _read_json(path, [])
    if not isinstance(payload, list):
        return []
    normalized = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        record = _normalize_approved_stream_record(item)
        if record is not None:
            record["tenant_id"] = _normalize_tenant_id(record.get("tenant_id"))
            normalized.append(record)
    return normalized


def get_approved_streams(tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    return [item for item in load_approved_streams(tenant_id=tenant_id) if _normalize_tenant_id(item.get("tenant_id")) == normalized_tenant_id]


def save_approved_streams(streams: List[Dict[str, object]], *, admin_id: Optional[str] = None, tenant_id: Optional[str] = None) -> None:
    resolved_admin_id = _resolve_admin_id(admin_id=admin_id, tenant_id=tenant_id)
    path = _tenant_file_path(resolved_admin_id, "approved_streams.json") if resolved_admin_id else APPROVED_STREAMS_PATH
    _write_json(path, streams)


def remove_approved_stream(stream_id: str, tenant_id: Optional[str] = None) -> None:
    streams = load_approved_streams(tenant_id=tenant_id)
    filtered = [
        item
        for item in streams
        if not (
            str(item.get("stream_id")) == str(stream_id)
            and _normalize_tenant_id(item.get("tenant_id")) == _normalize_tenant_id(tenant_id)
        )
    ]
    if len(filtered) != len(streams):
        save_approved_streams(filtered, tenant_id=tenant_id)


def approve_stream_mapping(
    stream: Dict[str, str],
    nation_id: str,
    competition_id: str,
    home_club_id: str,
    away_club_id: str,
    kickoff_label: str = "",
    tenant_id: Optional[str] = None,
) -> Dict[str, object]:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    nation = get_nation(nation_id, tenant_id=normalized_tenant_id)
    competition = get_competition(competition_id, tenant_id=normalized_tenant_id)
    home_club = get_club(home_club_id, tenant_id=normalized_tenant_id)
    away_club = get_club(away_club_id, tenant_id=normalized_tenant_id)

    if nation is None:
        raise ValueError("Nation not found.")
    if competition is None:
        raise ValueError("Competition not found.")
    if home_club is None or away_club is None:
        raise ValueError("Both home and away clubs are required.")

    stream_id = str(stream.get("id") or "").strip()
    if not stream_id:
        raise ValueError("Stream id is required.")

    normalized_kickoff = _normalize_name(kickoff_label) if kickoff_label else ""
    mapping = {
        "tenant_id": normalized_tenant_id,
        "stream_id": stream_id,
        "raw_name": str(stream.get("name") or "").strip(),
        "stream_url": str(stream.get("url") or "").strip(),
        "stream_logo": str(stream.get("logo") or "").strip(),
        "last_known_url": str(stream.get("url") or "").strip(),
        "last_known_logo": str(stream.get("logo") or "").strip(),
        "nation_id": nation["id"],
        "nation": nation["name"],
        "nation_logo": nation.get("logo_url", ""),
        "competition_id": competition["id"],
        "competition_name": competition["name"],
        "competition_logo": competition.get("logo_url", ""),
        "home_club_id": home_club["id"],
        "home_club": home_club["name"],
        "home_club_logo": home_club.get("logo_url", ""),
        "away_club_id": away_club["id"],
        "away_club": away_club["name"],
        "away_club_logo": away_club.get("logo_url", ""),
        "kickoff_label": normalized_kickoff,
        "match_label": normalized_kickoff or f"{home_club['name']} vs {away_club['name']}",
        "updated_at": utc_now_iso(),
    }

    streams = [
        item
        for item in load_approved_streams(tenant_id=normalized_tenant_id)
        if not (
            str(item.get("stream_id")) == stream_id
            and _normalize_tenant_id(item.get("tenant_id")) == normalized_tenant_id
        )
    ]
    streams.append(mapping)
    streams.sort(
        key=lambda item: (
            str(item.get("nation") or "").lower(),
            str(item.get("competition_name") or "").lower(),
            str(item.get("match_label") or "").lower(),
        )
    )
    save_approved_streams(streams, tenant_id=normalized_tenant_id)
    return mapping


def enrich_approved_streams(current_streams: List[Dict[str, str]], tenant_id: Optional[str] = None) -> List[Dict[str, object]]:
    metadata = load_metadata(tenant_id=tenant_id)
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    api_base_url = get_api_base_url()
    nations = {item["id"]: item for item in metadata["nations"] if item.get("id") and item.get("tenant_id") == normalized_tenant_id}
    competitions = {
        item["id"]: item for item in metadata["competitions"] if item.get("id") and item.get("tenant_id") == normalized_tenant_id
    }
    clubs = {item["id"]: item for item in metadata["clubs"] if item.get("id") and item.get("tenant_id") == normalized_tenant_id}
    current_by_id = {
        str(item.get("id")): item for item in current_streams if str(item.get("id") or "").strip()
    }

    enriched: List[Dict[str, object]] = []
    for mapping in get_approved_streams(tenant_id=normalized_tenant_id):
        stream_id = str(mapping.get("stream_id") or "").strip()
        nation = nations.get(str(mapping.get("nation_id") or "")) or {
            "id": str(mapping.get("nation_id") or ""),
            "name": str(mapping.get("nation") or ""),
            "logo_url": str(mapping.get("nation_logo") or ""),
        }
        competition = competitions.get(str(mapping.get("competition_id") or "")) or {
            "id": str(mapping.get("competition_id") or ""),
            "name": str(mapping.get("competition_name") or ""),
            "logo_url": str(mapping.get("competition_logo") or ""),
            "type": "league",
        }
        home_club = clubs.get(str(mapping.get("home_club_id") or "")) or {
            "id": str(mapping.get("home_club_id") or ""),
            "name": str(mapping.get("home_club") or ""),
            "logo_url": str(mapping.get("home_club_logo") or ""),
        }
        away_club = clubs.get(str(mapping.get("away_club_id") or "")) or {
            "id": str(mapping.get("away_club_id") or ""),
            "name": str(mapping.get("away_club") or ""),
            "logo_url": str(mapping.get("away_club_logo") or ""),
        }

        if not nation.get("name") or not competition.get("name") or not home_club.get("name") or not away_club.get("name"):
            continue

        current_stream = current_by_id.get(stream_id, {})
        stream_url = str(current_stream.get("url") or mapping.get("stream_url") or mapping.get("last_known_url") or "")
        if not stream_url:
            continue

        raw_name = str(current_stream.get("name") or mapping.get("raw_name") or "")
        stream_logo = normalize_logo_url(
            current_stream.get("logo") or mapping.get("stream_logo") or mapping.get("last_known_logo") or "",
            base_url=api_base_url,
        )
        kickoff_label = str(mapping.get("kickoff_label") or "").strip()
        match_label = kickoff_label or f"{home_club['name']} vs {away_club['name']}"

        enriched.append(
            {
                "tenant_id": normalized_tenant_id,
                "stream_id": stream_id,
                "raw_name": raw_name,
                "stream_url": stream_url,
                "url": stream_url,
                "stream_logo": stream_logo,
                "nation_id": nation["id"],
                "nation_name": nation["name"],
                "nation": nation["name"],
                "nation_logo": normalize_logo_url(nation.get("logo_url", ""), base_url=api_base_url),
                "competition_id": competition["id"],
                "competition_name": competition["name"],
                "competition_type": competition.get("type", "league"),
                "competition_logo": normalize_logo_url(competition.get("logo_url", ""), base_url=api_base_url),
                "home_club_id": home_club["id"],
                "home_club_name": home_club["name"],
                "home_club": home_club["name"],
                "home_club_logo": normalize_logo_url(home_club.get("logo_url", ""), base_url=api_base_url),
                "away_club_id": away_club["id"],
                "away_club_name": away_club["name"],
                "away_club": away_club["name"],
                "away_club_logo": normalize_logo_url(away_club.get("logo_url", ""), base_url=api_base_url),
                "kickoff_label": kickoff_label,
                "match_label": match_label,
            }
        )

    enriched.sort(
        key=lambda item: (
            str(item.get("nation_name", "")).lower(),
            str(item.get("competition_name", "")).lower(),
            str(item.get("match_label", "")).lower(),
        )
    )
    return enriched


def build_catalog(enriched_streams: List[Dict[str, object]]) -> List[Dict[str, object]]:
    nations: Dict[str, Dict[str, object]] = {}

    for stream in enriched_streams:
        nation_id = str(stream["nation_id"])
        competition_id = str(stream["competition_id"])

        nation_entry = nations.setdefault(
            nation_id,
            {
                "id": nation_id,
                "name": stream["nation_name"],
                "logo": stream.get("nation_logo", ""),
                "competitions": {},
            },
        )

        competitions = nation_entry["competitions"]
        competition_entry = competitions.setdefault(
            competition_id,
            {
                "id": competition_id,
                "name": stream["competition_name"],
                "type": stream.get("competition_type", "league"),
                "logo": stream.get("competition_logo", ""),
                "matches": [],
            },
        )

        competition_entry["matches"].append(
            {
                "stream_id": stream["stream_id"],
                "raw_name": stream["raw_name"],
                "stream_url": stream["stream_url"],
                "url": stream["stream_url"],
                "stream_logo": stream.get("stream_logo", ""),
                "competition_name": stream["competition_name"],
                "competition_logo": stream.get("competition_logo", ""),
                "match_label": stream["match_label"],
                "kickoff_label": stream.get("kickoff_label", ""),
                "home_team_name": stream["home_club_name"],
                "home_team_logo": stream.get("home_club_logo", ""),
                "away_team_name": stream["away_club_name"],
                "away_team_logo": stream.get("away_club_logo", ""),
                "home_club": {
                    "id": stream["home_club_id"],
                    "name": stream["home_club_name"],
                    "logo": stream.get("home_club_logo", ""),
                },
                "away_club": {
                    "id": stream["away_club_id"],
                    "name": stream["away_club_name"],
                    "logo": stream.get("away_club_logo", ""),
                },
                "tenant_id": stream.get("tenant_id", DEFAULT_TENANT_ID),
            }
        )

    result = []
    for nation in sorted(nations.values(), key=lambda item: str(item["name"]).lower()):
        competitions = nation.pop("competitions")
        nation["competitions"] = sorted(
            competitions.values(),
            key=lambda item: str(item["name"]).lower(),
        )
        result.append(nation)
    return result
