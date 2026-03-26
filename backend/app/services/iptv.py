from __future__ import annotations

import logging
import re
import time
from typing import Dict, List, Optional, Tuple

import requests

from app.logo_utils import normalize_logo_url
from app.settings import IPTVSettings

M3U_EXTINF_RE = re.compile(r"#EXTINF:.*?,(?P<name>.*)$")
M3U_TVG_ID_RE = re.compile(r'tvg-id="(?P<id>[^"]*)"')
M3U_GROUP_RE = re.compile(r'group-title="(?P<group>[^"]*)"')
M3U_LOGO_RE = re.compile(r'tvg-logo="(?P<logo>[^"]*)"')

_CACHE_BY_KEY: Dict[str, Dict[str, object]] = {}
logger = logging.getLogger(__name__)


class IPTVAuthError(RuntimeError):
    pass


class IPTVProviderError(RuntimeError):
    pass


def list_streams(
    settings: IPTVSettings, force_refresh: bool = False
) -> List[Dict[str, str]]:
    streams, _, _ = _get_stream_cache(settings, force_refresh=force_refresh)
    return streams


def get_streams_page(
    settings: IPTVSettings,
    page: int,
    page_size: int,
    category: Optional[str] = None,
    include_url: bool = False,
) -> Tuple[List[Dict[str, str]], int]:
    streams, by_group, _ = _get_stream_cache(settings, force_refresh=False)

    if category:
        selected = by_group.get(category, []) if isinstance(by_group, dict) else []
    else:
        selected = streams

    total = len(selected)
    start = max(page - 1, 0) * page_size
    end = start + page_size
    items = selected[start:end]

    if include_url:
        return items, total

    light_items = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "group": item.get("group"),
            "logo": item.get("logo"),
        }
        for item in items
    ]
    return light_items, total


def get_stream_by_id(settings: IPTVSettings, stream_id: str) -> Optional[Dict[str, str]]:
    _, _, by_id = _get_stream_cache(settings, force_refresh=False)
    if isinstance(by_id, dict) and stream_id in by_id:
        return by_id[stream_id]
    return None


def get_cache_info() -> Dict[str, object]:
    total_streams = sum(len(entry.get("streams", [])) for entry in _CACHE_BY_KEY.values())
    latest_fetch = max((float(entry.get("fetched_at", 0.0)) for entry in _CACHE_BY_KEY.values()), default=0.0)
    return {
        "total": total_streams,
        "fetched_at": latest_fetch,
        "provider_scopes": len(_CACHE_BY_KEY),
    }


def _cache_key(settings: IPTVSettings) -> str:
    return "|".join(
        [
            str(settings.xtream_server_url or "").strip(),
            str(settings.xtream_username or "").strip(),
            str(settings.xtream_password or "").strip(),
            str(settings.m3u_playlist_url or "").strip(),
            str(settings.cache_ttl_seconds or 300),
        ]
    )


def _get_stream_cache(
    settings: IPTVSettings, force_refresh: bool = False
) -> Tuple[List[Dict[str, str]], Dict[str, List[Dict[str, str]]], Dict[str, Dict[str, str]]]:
    cache_key = _cache_key(settings)
    cache = _CACHE_BY_KEY.setdefault(
        cache_key,
        {"streams": [], "fetched_at": 0.0, "by_group": {}, "by_id": {}},
    )
    ttl = settings.cache_ttl_seconds
    now = time.time()
    fetched_at = float(cache.get("fetched_at", 0.0))

    if not force_refresh and cache.get("streams") and (now - fetched_at) < ttl:
        return (
            cache.get("streams", []),
            cache.get("by_group", {}),
            cache.get("by_id", {}),
        )

    if settings.m3u_playlist_url:
        streams = _list_streams_from_m3u(settings.m3u_playlist_url)
    elif (
        settings.xtream_server_url
        and settings.xtream_username
        and settings.xtream_password
    ):
        streams = _list_streams_from_xtream(
            settings.xtream_server_url,
            settings.xtream_username,
            settings.xtream_password,
        )
    else:
        streams = []

    by_group: Dict[str, List[Dict[str, str]]] = {}
    by_id: Dict[str, Dict[str, str]] = {}
    for item in streams:
        stream_id = str(item.get("id"))
        by_id[stream_id] = item
        group = item.get("group")
        if group:
            by_group.setdefault(group, []).append(item)

    cache["streams"] = streams
    cache["fetched_at"] = now
    cache["by_group"] = by_group
    cache["by_id"] = by_id

    return streams, by_group, by_id


def _list_streams_from_m3u(url: str) -> List[Dict[str, str]]:
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response else None
        if status in (401, 403):
            raise IPTVAuthError("M3U authorization failed.") from exc
        raise IPTVProviderError("M3U provider error.") from exc
    except requests.RequestException as exc:
        raise IPTVProviderError("M3U provider connection failed.") from exc

    lines = [line.strip() for line in response.text.splitlines() if line.strip()]
    results: List[Dict[str, str]] = []

    current_name: Optional[str] = None
    current_id: Optional[str] = None
    current_group: Optional[str] = None
    current_logo: Optional[str] = None

    for line in lines:
        if line.startswith("#EXTINF"):
            name_match = M3U_EXTINF_RE.search(line)
            current_name = name_match.group("name").strip() if name_match else "Unknown"
            id_match = M3U_TVG_ID_RE.search(line)
            current_id = id_match.group("id").strip() if id_match else None
            group_match = M3U_GROUP_RE.search(line)
            current_group = group_match.group("group").strip() if group_match else None
            logo_match = M3U_LOGO_RE.search(line)
            current_logo = logo_match.group("logo").strip() if logo_match else None
            continue

        if line.startswith("#"):
            continue

        if current_name:
            stream_id = current_id or str(len(results) + 1)
            item = {"id": stream_id, "name": current_name, "url": line}
            if current_group:
                item["group"] = current_group
            if current_logo:
                item["logo"] = normalize_logo_url(current_logo)
            results.append(item)

        current_name = None
        current_id = None
        current_group = None
        current_logo = None

    return results


def _list_streams_from_xtream(
    server_url: str, username: str, password: str
) -> List[Dict[str, str]]:
    base = server_url.rstrip("/")
    api_url = f"{base}/player_api.php"

    try:
        auth_response = requests.get(
            api_url,
            params={"username": username, "password": password},
            timeout=15,
        )
        auth_response.raise_for_status()
        auth_payload = auth_response.json()
        if isinstance(auth_payload, dict):
            user_info = auth_payload.get("user_info") or {}
            auth = user_info.get("auth")
            if auth in (0, "0", False):
                raise IPTVAuthError("Xtream authentication failed.")
        else:
            raise IPTVProviderError("Unexpected Xtream auth response.")
    except IPTVAuthError:
        raise
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response else None
        if status in (401, 403):
            raise IPTVAuthError("Xtream authentication failed.") from exc
        raise IPTVProviderError("Xtream provider error.") from exc
    except requests.RequestException as exc:
        raise IPTVProviderError("Xtream provider connection failed.") from exc
    except ValueError as exc:
        raise IPTVProviderError("Xtream provider returned invalid JSON.") from exc

    try:
        response = requests.get(
            api_url,
            params={
                "username": username,
                "password": password,
                "action": "get_live_streams",
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response else None
        if status in (401, 403):
            raise IPTVAuthError("Xtream authentication failed.") from exc
        raise IPTVProviderError("Xtream provider error.") from exc
    except requests.RequestException as exc:
        raise IPTVProviderError("Xtream provider connection failed.") from exc

    data = response.json()
    if not isinstance(data, list):
        raise IPTVProviderError("Unexpected Xtream API response.")
    if data and isinstance(data[0], dict):
        logger.debug("Xtream live streams response: count=%s keys=%s", len(data), sorted(data[0].keys())[:12])
    else:
        logger.debug("Xtream live streams response: count=%s", len(data))

    results: List[Dict[str, str]] = []
    for entry in data:
        stream_id = str(entry.get("stream_id", ""))
        name = entry.get("name") or f"Channel {stream_id}"
        if not stream_id:
            continue

        url = f"{base}/live/{username}/{password}/{stream_id}.m3u8"
        item = {"id": stream_id, "name": name, "url": url}
        if entry.get("category_name"):
            item["group"] = str(entry.get("category_name"))
        if entry.get("stream_icon"):
            item["logo"] = normalize_logo_url(entry.get("stream_icon"))
        results.append(item)

    return results
