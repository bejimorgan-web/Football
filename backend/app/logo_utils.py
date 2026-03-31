from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Optional

from app.api_config import get_api_base_url

STATIC_ROOT = Path(__file__).resolve().parent / "static"
STATIC_LOGOS_DIR = STATIC_ROOT / "logos"
DEFAULT_LOGO_PLACEHOLDER = "https://via.placeholder.com/50"

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$")
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.(png|jpg|jpeg|webp|svg)$", re.IGNORECASE)
_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def ensure_static_logo_storage() -> None:
    STATIC_LOGOS_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_base_url(base_url: Optional[str] = None) -> str:
    return str(base_url or get_api_base_url() or "").strip().rstrip("/")


def _static_logo_url(filename: str, *, base_url: Optional[str] = None) -> str:
    return f"{_normalize_base_url(base_url)}/static/logos/{filename.lstrip('/')}"


def materialize_logo_data_url(data_url: str, *, base_url: Optional[str] = None) -> str:
    match = _DATA_URL_RE.match(str(data_url or "").strip())
    if not match:
        return str(data_url or "").strip()

    mime = match.group("mime").lower()
    extension = _EXTENSIONS.get(mime)
    if extension is None:
        return DEFAULT_LOGO_PLACEHOLDER

    try:
        content = base64.b64decode(match.group("data"), validate=False)
    except Exception:
        return DEFAULT_LOGO_PLACEHOLDER

    ensure_static_logo_storage()
    digest = hashlib.sha256(content).hexdigest()[:16]
    filename = f"inline-{digest}{extension}"
    target_path = STATIC_LOGOS_DIR / filename
    if not target_path.exists():
        target_path.write_bytes(content)
    return _static_logo_url(filename, base_url=base_url)


def normalize_logo_url(value: object, *, base_url: Optional[str] = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    if raw.startswith("data:image/"):
        return materialize_logo_data_url(raw, base_url=base_url)

    if raw.startswith(("http://", "https://")):
        return raw

    normalized_base_url = _normalize_base_url(base_url)

    if raw.startswith(("/assets/", "/branding/", "/cdn/branding/", "/static/")):
        return f"{normalized_base_url}{raw}"

    if raw.startswith(("assets/", "branding/", "cdn/branding/", "static/")):
        return f"{normalized_base_url}/{raw}"

    if _FILE_NAME_RE.match(raw):
        return _static_logo_url(raw, base_url=base_url)

    if raw.startswith("/"):
        return f"{normalized_base_url}{raw}"

    return f"{normalized_base_url}/{raw.lstrip('/')}"
