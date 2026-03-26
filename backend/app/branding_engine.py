from __future__ import annotations

import base64
import json
import re
import shutil
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageDraw

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = BACKEND_ROOT / "data"
STORAGE_ROOT = BACKEND_ROOT / "storage"
BRANDING_STORAGE_ROOT = STORAGE_ROOT / "branding"
BRANDING_CDN_ROOT = STORAGE_ROOT / "cdn" / "branding"
TENANT_BRANDING_TABLE_PATH = DATA_ROOT / "tenant_branding.json"

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_branding_storage() -> None:
    BRANDING_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    BRANDING_CDN_ROOT.mkdir(parents=True, exist_ok=True)
    TENANT_BRANDING_TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not TENANT_BRANDING_TABLE_PATH.exists():
        TENANT_BRANDING_TABLE_PATH.write_text("[]", encoding="utf-8")


def _read_table() -> List[Dict[str, object]]:
    ensure_branding_storage()
    try:
        payload = json.loads(TENANT_BRANDING_TABLE_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _write_table(items: List[Dict[str, object]]) -> None:
    ensure_branding_storage()
    TENANT_BRANDING_TABLE_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _tenant_dir(tenant_id: str) -> Path:
    path = BRANDING_STORAGE_ROOT / str(tenant_id or "default").strip()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tenant_cdn_dir(tenant_id: str) -> Path:
    path = BRANDING_CDN_ROOT / str(tenant_id or "default").strip()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _public_storage_url(tenant_id: str, filename: str) -> str:
    return f"/branding/{tenant_id}/{filename}"


def _public_cdn_url(tenant_id: str, filename: str) -> str:
    return f"/cdn/branding/{tenant_id}/{filename}"


def _default_record(tenant_id: str, app_name: str = "", primary_color: str = "#11B37C", secondary_color: str = "#7EE3AF") -> Dict[str, object]:
    return {
        "id": str(tenant_id),
        "tenant_id": str(tenant_id),
        "app_name": str(app_name or ""),
        "logo_original": "",
        "logo_storage_path": "",
        "primary_color": str(primary_color or "#11B37C"),
        "secondary_color": str(secondary_color or "#7EE3AF"),
        "favicon_path": "",
        "desktop_icon_path": "",
        "mobile_icon_path": "",
        "splash_screen_path": "",
        "updated_at": utc_now_iso(),
    }


def get_branding_record(tenant_id: str) -> Optional[Dict[str, object]]:
    return next((item for item in _read_table() if str(item.get("tenant_id") or "") == str(tenant_id or "")), None)


def upsert_branding_record(
    tenant_id: str,
    *,
    app_name: str = "",
    primary_color: str = "#11B37C",
    secondary_color: str = "#7EE3AF",
    patch: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    current = dict(get_branding_record(tenant_id) or _default_record(tenant_id, app_name=app_name, primary_color=primary_color, secondary_color=secondary_color))
    current.update(patch or {})
    current["tenant_id"] = str(tenant_id)
    current["id"] = str(current.get("id") or tenant_id)
    current["app_name"] = str(current.get("app_name") or app_name or "")
    current["primary_color"] = str(current.get("primary_color") or primary_color or "#11B37C")
    current["secondary_color"] = str(current.get("secondary_color") or secondary_color or "#7EE3AF")
    current["updated_at"] = utc_now_iso()
    items = [item for item in _read_table() if str(item.get("tenant_id") or "") != str(tenant_id)]
    items.append(current)
    _write_table(items)
    return current


def _decode_png_data_url(data_url: str) -> bytes:
    match = _DATA_URL_RE.match(str(data_url or "").strip())
    if not match:
        raise ValueError("Logo must be a PNG data URL.")
    if match.group("mime").lower() != "image/png":
        raise ValueError("Only PNG logos are supported.")
    try:
        return base64.b64decode(match.group("data"))
    except ValueError as exc:
        raise ValueError("Invalid PNG data.") from exc


def _contain_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    logo = image.copy()
    logo.thumbnail(size, Image.LANCZOS)
    offset = ((size[0] - logo.width) // 2, (size[1] - logo.height) // 2)
    canvas.paste(logo, offset, logo if logo.mode == "RGBA" else None)
    return canvas


def _save_ico(source: Image.Image, path: Path, sizes: List[tuple[int, int]]) -> None:
    sized = [_contain_image(source, size) for size in sizes]
    sized[0].save(path, format="ICO", sizes=sizes)


def _save_png(source: Image.Image, path: Path, size: tuple[int, int]) -> None:
    _contain_image(source, size).save(path, format="PNG")


def _copy_to_cdn(tenant_id: str, filenames: List[str]) -> None:
    storage_dir = _tenant_dir(tenant_id)
    cdn_dir = _tenant_cdn_dir(tenant_id)
    for filename in filenames:
        source = storage_dir / filename
        if source.exists():
            shutil.copy2(source, cdn_dir / filename)


def _generate_splash(source: Image.Image, path: Path, primary_color: str) -> None:
    splash = Image.new("RGBA", (1080, 1920), primary_color)
    logo = _contain_image(source, (480, 480))
    shadow = Image.new("RGBA", (560, 560), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.rounded_rectangle((0, 0, 560, 560), radius=80, fill=(255, 255, 255, 22))
    shadow_position = ((1080 - 560) // 2, (1920 - 560) // 2)
    splash.alpha_composite(shadow, shadow_position)
    logo_position = ((1080 - logo.width) // 2, (1920 - logo.height) // 2)
    splash.alpha_composite(logo, logo_position)
    splash.save(path, format="PNG")


def _generate_from_image(
    tenant_id: str,
    *,
    image: Image.Image,
    app_name: str,
    primary_color: str,
    secondary_color: str,
    logo_original: str,
) -> Dict[str, object]:
    ensure_branding_storage()
    tenant_dir = _tenant_dir(tenant_id)
    master_logo = _contain_image(image.convert("RGBA"), (1024, 1024))
    (tenant_dir / "logo.png").parent.mkdir(parents=True, exist_ok=True)
    master_logo.save(tenant_dir / "logo.png", format="PNG")
    _save_ico(master_logo, tenant_dir / "desktop_icon.ico", [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256)])
    _save_png(master_logo, tenant_dir / "mobile_icon.png", (512, 512))
    _save_ico(master_logo, tenant_dir / "favicon.ico", [(16, 16), (32, 32), (64, 64)])
    _save_png(master_logo, tenant_dir / "favicon-16.png", (16, 16))
    _save_png(master_logo, tenant_dir / "favicon-32.png", (32, 32))
    _save_png(master_logo, tenant_dir / "apple-touch-icon.png", (180, 180))
    _generate_splash(master_logo, tenant_dir / "splash.png", primary_color)
    _copy_to_cdn(
        tenant_id,
        [
            "logo.png",
            "desktop_icon.ico",
            "mobile_icon.png",
            "favicon.ico",
            "favicon-16.png",
            "favicon-32.png",
            "apple-touch-icon.png",
            "splash.png",
        ],
    )
    return upsert_branding_record(
        tenant_id,
        app_name=app_name,
        primary_color=primary_color,
        secondary_color=secondary_color,
        patch={
            "logo_original": logo_original,
            "logo_storage_path": _public_storage_url(tenant_id, "logo.png"),
            "favicon_path": _public_cdn_url(tenant_id, "favicon.ico"),
            "desktop_icon_path": _public_storage_url(tenant_id, "desktop_icon.ico"),
            "mobile_icon_path": _public_storage_url(tenant_id, "mobile_icon.png"),
            "splash_screen_path": _public_storage_url(tenant_id, "splash.png"),
        },
    )


def process_logo_upload(tenant_id: str, *, data_url: str, app_name: str, primary_color: str, secondary_color: str) -> Dict[str, object]:
    image = Image.open(BytesIO(_decode_png_data_url(data_url)))
    return _generate_from_image(
        tenant_id,
        image=image,
        app_name=app_name,
        primary_color=primary_color,
        secondary_color=secondary_color,
        logo_original="upload",
    )


def rebuild_branding_assets(tenant_id: str, *, app_name: str, primary_color: str, secondary_color: str) -> Dict[str, object]:
    logo_path = _tenant_dir(tenant_id) / "logo.png"
    if not logo_path.exists():
        raise ValueError("No tenant logo found to rebuild assets.")
    image = Image.open(logo_path)
    return _generate_from_image(
        tenant_id,
        image=image,
        app_name=app_name,
        primary_color=primary_color,
        secondary_color=secondary_color,
        logo_original="rebuild",
    )


def get_branding_response(tenant_id: str, *, app_name: str, logo_url: str, primary_color: str, secondary_color: str) -> Dict[str, object]:
    record = upsert_branding_record(
        tenant_id,
        app_name=app_name,
        primary_color=primary_color,
        secondary_color=secondary_color,
    )
    return {
        "tenant_id": tenant_id,
        "app_name": app_name,
        "logo_url": logo_url or str(record.get("logo_storage_path") or ""),
        "primary_color": primary_color,
        "secondary_color": secondary_color,
        "favicon_path": str(record.get("favicon_path") or ""),
        "desktop_icon_path": str(record.get("desktop_icon_path") or ""),
        "mobile_icon_path": str(record.get("mobile_icon_path") or ""),
        "splash_screen_path": str(record.get("splash_screen_path") or ""),
        "cdn_logo_url": _public_cdn_url(tenant_id, "logo.png") if (BRANDING_CDN_ROOT / tenant_id / "logo.png").exists() else "",
    }
