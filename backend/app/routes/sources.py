from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.iptv import IPTVAuthError, IPTVProviderError, list_streams
from app.settings import IPTVSettings
from app.sources_store import create_source, delete_source, get_source, list_sources

router = APIRouter(prefix="/sources", tags=["sources"])


class SourcePayload(BaseModel):
    name: str = Field(default="", min_length=1)
    type: str = Field(default="m3u")
    url: str = Field(default="", min_length=1)
    username: str = ""
    password: str = ""


def _build_iptv_settings(source: dict) -> IPTVSettings:
    source_type = str(source.get("type") or "").strip().lower()
    if source_type == "xtream":
        return IPTVSettings(
            xtream_server_url=str(source.get("url") or "").strip() or None,
            xtream_username=str(source.get("username") or "").strip() or None,
            xtream_password=str(source.get("password") or "") or None,
            cache_ttl_seconds=300,
        )
    return IPTVSettings(
        m3u_playlist_url=str(source.get("url") or "").strip() or None,
        cache_ttl_seconds=300,
    )


def _validate_source_payload(payload: SourcePayload) -> dict:
    source_type = str(payload.type or "").strip().lower()
    if source_type not in {"xtream", "m3u"}:
        raise HTTPException(status_code=400, detail="Source type must be either 'xtream' or 'm3u'.")

    source = {
        "name": payload.name.strip(),
        "type": source_type,
        "url": payload.url.strip(),
        "username": payload.username.strip(),
        "password": payload.password,
    }

    if not source["name"]:
        raise HTTPException(status_code=400, detail="Source name is required.")
    if not source["url"]:
        raise HTTPException(status_code=400, detail="Source URL is required.")
    if source_type == "xtream" and (not source["username"] or not source["password"]):
        raise HTTPException(status_code=400, detail="Xtream sources require username and password.")

    return source


@router.get("")
def get_sources():
    return {"items": list_sources()}


@router.post("")
def add_source(payload: SourcePayload):
    source = create_source(_validate_source_payload(payload))
    return {"item": source, "items": list_sources()}


@router.delete("/{source_id}")
def remove_source(source_id: str):
    removed = delete_source(source_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return {"deleted": True, "item": removed, "items": list_sources()}


@router.get("/{source_id}/streams")
def get_source_streams(source_id: str):
    source = get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")

    try:
        items = list_streams(_build_iptv_settings(source), force_refresh=True)
    except IPTVAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except IPTVProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "source": source,
        "items": items,
        "total": len(items),
    }
