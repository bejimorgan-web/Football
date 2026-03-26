from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Dict

from app.config import DEFAULT_API_URL
from app.server_config import load_server_config
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
API_CONFIG_PATH = DATA_DIR / "api_config.json"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_api_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if normalized.startswith("https//"):
        normalized = normalized.replace("https//", "https://", 1)
    elif normalized.startswith("http//"):
        normalized = normalized.replace("http//", "http://", 1)
    return normalized or load_server_config()["local_url"] or DEFAULT_API_URL


def get_runtime_public_api_url() -> str:
    server_config = load_server_config()
    return normalize_api_base_url(server_config["public_url"] or DEFAULT_API_URL)


def get_runtime_backend_api_url() -> str:
    server_config = load_server_config()
    return normalize_api_base_url(server_config["local_url"] or server_config["public_url"] or DEFAULT_API_URL)


def _normalize_endpoint_config(payload: object, *, fallback_url: str) -> Dict[str, object]:
    item = payload if isinstance(payload, dict) else {}
    raw_url = str(item.get("url") or fallback_url or "").strip()
    return {
        "url": normalize_api_base_url(raw_url) if raw_url else "",
        "api_token": str(item.get("api_token") or item.get("apiToken") or item.get("token") or "").strip(),
        "connected": item.get("connected") is True,
    }


def ensure_api_config_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not API_CONFIG_PATH.exists():
        default_public_url = get_runtime_public_api_url()
        default_backend_url = get_runtime_backend_api_url()
        API_CONFIG_PATH.write_text(
            json.dumps(
                {
                    "apiBaseUrl": default_public_url,
                    "backend_api": {
                        "url": default_backend_url,
                        "api_token": "",
                        "connected": False,
                    },
                    "public_api": {
                        "url": default_public_url,
                        "api_token": "",
                        "connected": False,
                    },
                    "updatedAt": _utc_now().isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def load_api_config() -> Dict[str, object]:
    ensure_api_config_storage()
    try:
        payload = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    server_config = load_server_config()
    legacy_public_url = str(payload.get("apiBaseUrl") or "").strip()
    default_public_url = get_runtime_public_api_url()
    default_backend_url = get_runtime_backend_api_url()
    raw_backend_api = payload.get("backend_api") or payload.get("backendApi")
    raw_public_api = payload.get("public_api") or payload.get("publicApi")
    backend_api = _normalize_endpoint_config(raw_backend_api, fallback_url=default_backend_url if raw_backend_api is None else "")
    public_api = _normalize_endpoint_config(
        raw_public_api,
        fallback_url=(legacy_public_url or default_public_url) if raw_public_api is None else "",
    )
    api_base_url = str(payload.get("apiBaseUrl") or public_api["url"] or default_public_url).strip()
    return {
        "apiBaseUrl": normalize_api_base_url(api_base_url) if api_base_url else default_public_url,
        "backend_api": backend_api,
        "public_api": public_api,
        "updatedAt": str(payload.get("updatedAt") or ""),
    }


def save_api_config(api_base_url: str = "", *, backend_api: object = None, public_api: object = None) -> Dict[str, object]:
    ensure_api_config_storage()
    current = load_api_config()
    next_public_source = public_api if public_api is not None else current.get("public_api")
    if api_base_url:
        next_public_source = {**(next_public_source if isinstance(next_public_source, dict) else {}), "url": api_base_url}
    payload = {
        "apiBaseUrl": normalize_api_base_url(api_base_url or str((current.get("public_api") or {}).get("url") or "")),
        "backend_api": _normalize_endpoint_config(
            backend_api if backend_api is not None else current.get("backend_api"),
            fallback_url=str((current.get("backend_api") or {}).get("url") or DEFAULT_API_URL),
        ),
        "public_api": _normalize_endpoint_config(
            next_public_source,
            fallback_url=str((current.get("public_api") or {}).get("url") or DEFAULT_API_URL),
        ),
        "updatedAt": _utc_now().isoformat(),
    }
    payload["apiBaseUrl"] = str(payload["public_api"]["url"])
    API_CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def get_api_base_url() -> str:
    return str(load_api_config().get("apiBaseUrl") or DEFAULT_API_URL)


def build_public_api_config() -> Dict[str, object]:
    payload = load_api_config()
    server_config = load_server_config()
    return {
        "apiBaseUrl": payload["apiBaseUrl"],
        "backend_api": {
            **payload["backend_api"],
            "token": payload["backend_api"]["api_token"],
        },
        "public_api": {
            **payload["public_api"],
            "token": payload["public_api"]["api_token"],
        },
        "backendApi": {
            **payload["backend_api"],
            "apiToken": payload["backend_api"]["api_token"],
            "token": payload["backend_api"]["api_token"],
        },
        "publicApi": {
            **payload["public_api"],
            "apiToken": payload["public_api"]["api_token"],
            "token": payload["public_api"]["api_token"],
        },
        "validUntil": (_utc_now() + timedelta(hours=12)).isoformat(),
        "serverMappings": {
            "public_url": server_config["public_url"],
            "local_url": server_config["local_url"],
        },
        "updatedAt": payload.get("updatedAt") or "",
    }
