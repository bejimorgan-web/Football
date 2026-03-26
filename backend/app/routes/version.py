from typing import Optional

from fastapi import APIRouter, Header, Query

from app.storage import get_api_version_payload, get_latest_apk_version, validate_admin_api_token, validate_tenant_access_token

router = APIRouter()


def _resolve_tenant_id(authorization: Optional[str], tenant_id: Optional[str]) -> Optional[str]:
    header_value = authorization if isinstance(authorization, str) else ""
    resolved_query_tenant = tenant_id if isinstance(tenant_id, str) else None
    if header_value and header_value.lower().startswith("bearer "):
        token = header_value.split(" ", 1)[1].strip()
        try:
            payload = validate_tenant_access_token(token)
            resolved = str(payload.get("tenant_id") or "").strip()
            if resolved:
                return resolved
        except ValueError:
            try:
                admin = validate_admin_api_token(token, require_server=False)
            except ValueError:
                admin = None
            if admin is not None:
                if str(admin.get("role") or "").strip().lower() == "master" and resolved_query_tenant:
                    return resolved_query_tenant
                resolved = str(admin.get("tenant_id") or "").strip()
                if resolved:
                    return resolved
    return resolved_query_tenant


@router.get("/api/version")
def api_version(
    authorization: Optional[str] = Header(default=None),
    tenant_id: Optional[str] = Query(default="master"),
    current_version: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default="unknown"),
    client: Optional[str] = Query(default="web"),
):
    resolved_tenant_id = _resolve_tenant_id(authorization, tenant_id) or "master"
    resolved_current_version = current_version if isinstance(current_version, str) else ""
    resolved_client = client if isinstance(client, str) and client.strip() else "web"
    resolved_platform = platform if isinstance(platform, str) and platform.strip() else "unknown"
    payload = get_api_version_payload(
        resolved_tenant_id,
        current_version=resolved_current_version,
        platform=resolved_platform,
        client=resolved_client,
    )
    latest_apk = get_latest_apk_version() or {}
    latest_version = str(latest_apk.get("version") or payload.get("mobile", {}).get("latest_version") or "0.1.0")
    update_url = str(latest_apk.get("file_path") or payload.get("mobile", {}).get("update_url") or "")
    force_update = bool(latest_apk.get("force_update"))
    payload["status"] = "ok"
    payload["version"] = str(payload.get("mobile", {}).get("current_version") or payload.get("version") or "0.1.0")
    payload["tenant"] = resolved_tenant_id
    payload["client"] = resolved_client
    payload["platform"] = resolved_platform
    payload["latest_version"] = latest_version
    payload["force_update"] = force_update
    payload["update_url"] = update_url
    mobile_payload = payload.get("mobile") if isinstance(payload.get("mobile"), dict) else {}
    mobile_payload["latest_version"] = latest_version
    mobile_payload["force_update"] = force_update
    mobile_payload["update_url"] = update_url
    payload["mobile"] = mobile_payload
    payload.setdefault("server", "Gito IPTV Backend")
    return payload
