from typing import Optional

from fastapi import APIRouter, Query

from app.auth import SINGLE_TENANT_ID
from app.storage import get_api_version_payload

router = APIRouter()


@router.get("/api/version")
def api_version(
    current_version: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default="unknown"),
    client: Optional[str] = Query(default="web"),
):
    resolved_current_version = current_version if isinstance(current_version, str) else ""
    resolved_client = client if isinstance(client, str) and client.strip() else "web"
    resolved_platform = platform if isinstance(platform, str) and platform.strip() else "unknown"
    payload = get_api_version_payload(
        SINGLE_TENANT_ID,
        current_version=resolved_current_version,
        platform=resolved_platform,
        client=resolved_client,
    )
    payload["status"] = "ok"
    payload["tenant"] = SINGLE_TENANT_ID
    payload["tenant_id"] = SINGLE_TENANT_ID
    payload["tenant_locked"] = False
    payload["client"] = resolved_client
    payload["platform"] = resolved_platform
    payload.setdefault("server", "Football Streaming Backend")
    return payload
