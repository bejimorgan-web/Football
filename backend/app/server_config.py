from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from app.config import DEFAULT_API_URL

SERVER_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "server_config.json"


def _normalize_url(value: str, fallback: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if normalized.startswith("https//"):
        normalized = normalized.replace("https//", "https://", 1)
    elif normalized.startswith("http//"):
        normalized = normalized.replace("http//", "http://", 1)
    return normalized or fallback


def load_server_config() -> Dict[str, str]:
    payload: Dict[str, object] = {}
    if SERVER_CONFIG_PATH.exists():
        try:
            data = json.loads(SERVER_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                payload = data
        except Exception:
            payload = {}

    public_url = _normalize_url(str(payload.get("public_url") or ""), DEFAULT_API_URL)
    local_url = _normalize_url(str(payload.get("local_url") or ""), "http://127.0.0.1:8000")
    return {
        "public_url": public_url,
        "local_url": local_url,
    }


def get_public_server_url() -> str:
    return load_server_config()["public_url"]


def get_local_server_url() -> str:
    return load_server_config()["local_url"]
