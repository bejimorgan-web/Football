from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SOURCES_PATH = DATA_DIR / "sources.json"

SOURCE_TYPES = {"xtream", "m3u"}


def ensure_sources_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SOURCES_PATH.exists():
        SOURCES_PATH.write_text("[]", encoding="utf-8")


def _read_sources() -> List[Dict[str, object]]:
    ensure_sources_storage()
    try:
        payload = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [_normalize_source(item) for item in payload if isinstance(item, dict)]


def _write_sources(items: List[Dict[str, object]]) -> None:
    ensure_sources_storage()
    SOURCES_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _normalize_source(item: Dict[str, object]) -> Dict[str, object]:
    source_type = str(item.get("type") or "").strip().lower()
    if source_type not in SOURCE_TYPES:
        source_type = "m3u"
    return {
        "id": str(item.get("id") or uuid4().hex).strip() or uuid4().hex,
        "name": str(item.get("name") or "Untitled Source").strip() or "Untitled Source",
        "type": source_type,
        "url": str(item.get("url") or "").strip(),
        "username": str(item.get("username") or "").strip(),
        "password": str(item.get("password") or ""),
    }


def list_sources() -> List[Dict[str, object]]:
    return _read_sources()


def create_source(payload: Dict[str, object]) -> Dict[str, object]:
    items = _read_sources()
    source = _normalize_source(payload)
    items.append(source)
    _write_sources(items)
    return source


def delete_source(source_id: str) -> Optional[Dict[str, object]]:
    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id:
        return None
    items = _read_sources()
    removed = next((item for item in items if str(item.get("id") or "") == normalized_source_id), None)
    if removed is None:
        return None
    _write_sources([item for item in items if str(item.get("id") or "") != normalized_source_id])
    return removed


def get_source(source_id: str) -> Optional[Dict[str, object]]:
    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id:
        return None
    return next((item for item in _read_sources() if str(item.get("id") or "") == normalized_source_id), None)
