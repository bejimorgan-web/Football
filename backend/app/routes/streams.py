from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.auth import SINGLE_TENANT_ID, require_mobile_context
from app.logo_utils import normalize_logo_url
from app.services.iptv import IPTVAuthError, IPTVProviderError, get_streams_page, list_streams
from app.storage import (
    build_catalog,
    create_stream_token,
    enrich_approved_streams,
    get_device_status,
    get_approved_streams,
    get_provider_record,
    list_group_channels,
    list_provider_groups,
    list_provider_records,
    load_approved_streams,
    load_provider_settings,
    remove_approved_stream,
    save_approved_streams,
    sync_provider_catalog,
)

router = APIRouter()


def _request_base_url(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


def _normalize_mobile_logo_fields(item: Dict[str, object], *, base_url: str) -> Dict[str, object]:
    normalized = dict(item)
    for key in ("nation_logo", "competition_logo", "home_club_logo", "away_club_logo", "stream_logo", "logo", "logo_url"):
        if key in normalized:
            normalized[key] = normalize_logo_url(normalized.get(key), base_url=base_url)
    return normalized


def _normalize_mobile_catalog(catalog: List[Dict[str, object]], *, base_url: str) -> List[Dict[str, object]]:
    normalized_catalog: List[Dict[str, object]] = []
    for nation in catalog:
        normalized_nation = dict(nation)
        normalized_nation["logo"] = normalize_logo_url(normalized_nation.get("logo"), base_url=base_url)
        competitions = []
        for competition in nation.get("competitions", []):
            normalized_competition = dict(competition)
            normalized_competition["logo"] = normalize_logo_url(normalized_competition.get("logo"), base_url=base_url)
            matches = []
            for match in competition.get("matches", []):
                normalized_match = _normalize_mobile_logo_fields(match, base_url=base_url)
                home_club = dict(normalized_match.get("home_club") or {})
                away_club = dict(normalized_match.get("away_club") or {})
                if home_club:
                    home_club["logo"] = normalize_logo_url(home_club.get("logo"), base_url=base_url)
                    normalized_match["home_club"] = home_club
                if away_club:
                    away_club["logo"] = normalize_logo_url(away_club.get("logo"), base_url=base_url)
                    normalized_match["away_club"] = away_club
                matches.append(normalized_match)
            normalized_competition["matches"] = matches
            competitions.append(normalized_competition)
        normalized_nation["competitions"] = competitions
        normalized_catalog.append(normalized_nation)
    return normalized_catalog


class StreamCompatPayload(BaseModel):
    stream_id: str
    match_label: str = ""
    competition_name: str = ""
    competition_logo: str = ""
    home_club_name: str = ""
    home_club_logo: str = ""
    away_club_name: str = ""
    away_club_logo: str = ""
    stream_url: str = ""
    tenant_id: str = SINGLE_TENANT_ID


def _require_settings(tenant_id: Optional[str] = None):
    settings = load_provider_settings(tenant_id=tenant_id)
    if settings is None:
        raise HTTPException(status_code=503, detail="Backend is not configured.")
    return settings


def _load_provider_streams(tenant_id: Optional[str] = None, force_refresh: bool = False):
    settings = load_provider_settings(tenant_id=tenant_id)
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
    return [{"provider_id": "active", "id": "active", "active": True, "status": "active"}]


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


def _enforce_device_access(device_id: Optional[str], **status_kwargs) -> None:
    if not device_id:
        return
    try:
        status = get_device_status(device_id=device_id, touch=True, **status_kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not status.get("is_allowed"):
        raise HTTPException(status_code=403, detail=str(status.get("message") or "Access denied."))


@router.get("/")
def all_streams(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    category: Optional[str] = None,
    include_url: bool = False,
):
    settings = load_provider_settings()
    if settings is None:
        items = get_approved_streams()
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return {"items": items[start:end], "page": page, "page_size": page_size, "total": total}
    try:
        items, total = get_streams_page(
            settings=settings,
            page=page,
            page_size=page_size,
            category=category,
            include_url=include_url,
        )
    except IPTVAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except IPTVProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.post("/add")
def add_stream(payload: StreamCompatPayload):
    tenant_id = SINGLE_TENANT_ID
    streams = load_approved_streams(tenant_id=tenant_id)
    record = {
        "tenant_id": tenant_id,
        "stream_id": str(payload.stream_id).strip(),
        "match_label": str(payload.match_label).strip(),
        "competition_name": str(payload.competition_name).strip(),
        "competition_logo": str(payload.competition_logo).strip(),
        "home_club_name": str(payload.home_club_name).strip(),
        "home_club_logo": str(payload.home_club_logo).strip(),
        "away_club_name": str(payload.away_club_name).strip(),
        "away_club_logo": str(payload.away_club_logo).strip(),
        "stream_url": str(payload.stream_url).strip(),
        "last_known_url": str(payload.stream_url).strip(),
    }
    streams = [
        item
        for item in streams
        if not (
            str(item.get("stream_id") or "").strip() == record["stream_id"]
            and str(item.get("tenant_id") or "").strip() == tenant_id
        )
    ]
    streams.append(record)
    save_approved_streams(streams, tenant_id=tenant_id)
    return {"status": "ok", "item": record}


@router.delete("/{stream_id}")
def delete_stream(stream_id: str):
    remove_approved_stream(stream_id, tenant_id=SINGLE_TENANT_ID)
    return {"status": "ok", "stream_id": stream_id, "tenant_id": SINGLE_TENANT_ID}


@router.get("/approved")
def approved_streams(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    include_url: bool = False,
    device_id: Optional[str] = None,
    tenant_id: str = Query(SINGLE_TENANT_ID),
    _: None = Depends(require_mobile_context),
):
    context = getattr(request.state, "mobile_context", {})
    scoped_tenant_id = context.get("tenant_id") or SINGLE_TENANT_ID
    _enforce_device_access(device_id, tenant_id=scoped_tenant_id)
    request_base_url = _request_base_url(request)
    enriched = [
        _normalize_mobile_logo_fields(item, base_url=request_base_url)
        for item in enrich_approved_streams(
            _load_provider_streams(tenant_id=scoped_tenant_id, force_refresh=False),
            tenant_id=scoped_tenant_id,
        )
    ]
    total = len(enriched)
    start = (page - 1) * page_size
    end = start + page_size
    items = enriched[start:end]

    if not include_url:
        items = [
            {
                "stream_id": item.get("stream_id"),
                "match_label": item.get("match_label"),
                "competition_name": item.get("competition_name"),
                "competition_logo": item.get("competition_logo"),
                "home_club_name": item.get("home_club_name"),
                "home_club_logo": item.get("home_club_logo"),
                "away_club_name": item.get("away_club_name"),
                "away_club_logo": item.get("away_club_logo"),
            }
            for item in items
        ]

    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/leagues")
def streams_by_league(request: Request, include_url: bool = False, tenant_id: str = Query(SINGLE_TENANT_ID), _: None = Depends(require_mobile_context)) -> Dict[str, List[Dict]]:
    context = getattr(request.state, "mobile_context", {})
    scoped_tenant_id = context.get("tenant_id") or SINGLE_TENANT_ID
    catalog = build_catalog(enrich_approved_streams(_load_provider_streams(tenant_id=scoped_tenant_id, force_refresh=False), tenant_id=scoped_tenant_id))
    result: Dict[str, List[Dict]] = {}
    for nation in catalog:
        for competition in nation["competitions"]:
            result[competition["name"]] = competition["matches"] if include_url else [
                {
                    "stream_id": match["stream_id"],
                    "match_label": match["match_label"],
                    "home_club": match["home_club"],
                    "away_club": match["away_club"],
                }
                for match in competition["matches"]
            ]
    return result


@router.get("/catalog")
def match_catalog(
    request: Request,
    device_id: Optional[str] = None,
    tenant_id: str = Query(SINGLE_TENANT_ID),
    include_url: bool = False,
    _: None = Depends(require_mobile_context),
):
    context = getattr(request.state, "mobile_context", {})
    scoped_tenant_id = context.get("tenant_id") or SINGLE_TENANT_ID
    _enforce_device_access(device_id, tenant_id=scoped_tenant_id)
    enriched = enrich_approved_streams(_load_provider_streams(tenant_id=scoped_tenant_id, force_refresh=False), tenant_id=scoped_tenant_id)
    catalog = _normalize_mobile_catalog(build_catalog(enriched), base_url=_request_base_url(request))
    if not include_url:
        for nation in catalog:
            for competition in nation["competitions"]:
                for match in competition["matches"]:
                    match.pop("url", None)
                    match.pop("stream_url", None)
    return {"items": catalog}


@router.get("/token/{stream_id}")
def stream_token(
    request: Request,
    stream_id: str,
    device_id: str = Query(...),
    tenant_id: str = Query(SINGLE_TENANT_ID),
    country: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    vpn_active: Optional[bool] = False,
    secure_device: Optional[bool] = True,
    app_signature_valid: Optional[bool] = True,
    _: None = Depends(require_mobile_context),
):
    context = getattr(request.state, "mobile_context", {})
    scoped_tenant_id = context.get("tenant_id") or SINGLE_TENANT_ID
    _enforce_device_access(
        device_id,
        tenant_id=scoped_tenant_id,
        country=country or "",
        device_fingerprint=device_fingerprint or "",
        vpn_active=bool(vpn_active),
        secure_device=bool(secure_device),
        app_signature_valid=bool(app_signature_valid),
    )
    try:
        payload = create_stream_token(device_id=device_id, stream_id=stream_id, tenant_id=scoped_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"stream_url": f"/play/{payload['token']}", "expires_in": 60}
