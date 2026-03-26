from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_admin_context
from app.routes.admin import _load_provider_streams, _scoped_admin_id, _scoped_tenant_id, get_active_providers, get_group_channels, get_provider_groups
from app.services.provider_parser import normalize_groups

router = APIRouter(tags=["provider"])

PROVIDER_ACCESS = Depends(require_admin_context)


@router.get("/provider/groups")
def provider_groups(request: Request, provider_id: str = Query("active"), tenant_id: Optional[str] = Query(None), _: dict = PROVIDER_ACCESS):
    scoped_admin_id = _scoped_admin_id(request)
    scoped_tenant_id = _scoped_tenant_id(request, tenant_id)
    active_providers = get_active_providers(admin_id=scoped_admin_id, tenant_id=scoped_tenant_id)
    provider_active = any(str(item.get("provider_id") or item.get("id") or "") == str(provider_id or "") and bool(item.get("active")) for item in active_providers)
    streams = _load_provider_streams(request, tenant_id=tenant_id, force_refresh=False) if provider_active else []
    groups = get_provider_groups(provider_id, streams, provider_active=provider_active, admin_id=scoped_admin_id, tenant_id=scoped_tenant_id) if provider_active else []
    channels = []
    for group in groups:
        channels.extend(
            get_group_channels(
                str(group.get("group_id") or group.get("id") or ""),
                streams,
                provider_active=provider_active,
                provider_id=provider_id,
                admin_id=scoped_admin_id,
                tenant_id=scoped_tenant_id,
            )
        )
    return {"items": normalize_groups(groups, channels)}
