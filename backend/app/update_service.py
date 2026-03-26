from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parent.parent
UPDATES_DIR = BASE_DIR / "updates"
UPDATE_FILES_DIR = UPDATES_DIR / "files"
LATEST_METADATA_PATH = UPDATES_DIR / "latest.json"
VERSION_HISTORY_PATH = UPDATES_DIR / "versions.json"
LATEST_WINDOWS_YML_PATH = UPDATES_DIR / "latest.yml"
LATEST_MAC_YML_PATH = UPDATES_DIR / "latest-mac.yml"
LATEST_LINUX_YML_PATH = UPDATES_DIR / "latest-linux.yml"

MAX_UPDATE_SIZE_BYTES = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".exe": "win32",
    ".dmg": "darwin",
    ".appimage": "linux",
}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[\.-][0-9A-Za-z]+)*$")
DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def default_update_metadata() -> Dict[str, object]:
    today = date.today().isoformat()
    return {
        "version": "0.1.0",
        "release_date": today,
        "release_notes": "Initial desktop release.",
        "mandatory": False,
        "minimum_supported_version": "0.0.0",
        "download_url": "",
        "download_name": "",
        "download_size": 0,
        "sha512": "",
        "platform": "",
        "files": {},
        "published_at": utc_now_iso(),
    }


def ensure_update_storage() -> None:
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    UPDATE_FILES_DIR.mkdir(parents=True, exist_ok=True)
    if not LATEST_METADATA_PATH.exists():
        _write_json(LATEST_METADATA_PATH, default_update_metadata())
    if not VERSION_HISTORY_PATH.exists():
        _write_json(VERSION_HISTORY_PATH, [])
    _sync_update_feed_files(load_latest_metadata())


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def semver_key(value: str) -> Tuple[int, int, int, int]:
    pieces = []
    for chunk in str(value or "").replace("-", ".").split("."):
        if chunk.isdigit():
            pieces.append(int(chunk))
        else:
            digits = "".join(character for character in chunk if character.isdigit())
            pieces.append(int(digits) if digits else 0)
    return tuple(pieces[:4] + [0] * max(0, 4 - len(pieces)))


def infer_platform_from_filename(filename: str) -> str:
    suffix = Path(str(filename or "")).suffix.lower()
    platform = ALLOWED_EXTENSIONS.get(suffix)
    if not platform:
        raise ValueError("Unsupported update file type. Allowed: .exe, .dmg, .AppImage")
    return platform


def load_latest_metadata() -> Dict[str, object]:
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    UPDATE_FILES_DIR.mkdir(parents=True, exist_ok=True)
    if not LATEST_METADATA_PATH.exists():
        _write_json(LATEST_METADATA_PATH, default_update_metadata())
    payload = _read_json(LATEST_METADATA_PATH, default_update_metadata())
    if not isinstance(payload, dict):
        payload = default_update_metadata()
    metadata = {**default_update_metadata(), **payload}
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    metadata["files"] = {
        str(platform): normalize_file_entry(entry)
        for platform, entry in files.items()
        if isinstance(entry, dict)
    }
    metadata["mandatory"] = bool(metadata.get("mandatory"))
    metadata["release_date"] = str(metadata.get("release_date") or date.today().isoformat())
    metadata["published_at"] = str(metadata.get("published_at") or utc_now_iso())
    metadata["version"] = str(metadata.get("version") or "0.1.0")
    metadata["minimum_supported_version"] = str(
        metadata.get("minimum_supported_version") or (metadata["version"] if metadata["mandatory"] else "0.0.0")
    )
    return _with_resolved_download(metadata, None)


def save_latest_metadata(payload: Dict[str, object], *, append_history: bool = False) -> Dict[str, object]:
    ensure_update_storage()
    metadata = {**default_update_metadata(), **(payload or {})}
    metadata["version"] = str(metadata.get("version") or "0.1.0").strip()
    if not SEMVER_RE.match(metadata["version"]):
        raise ValueError("Version must use semantic versioning, for example 1.1.0")
    metadata["release_date"] = str(metadata.get("release_date") or date.today().isoformat())
    metadata["published_at"] = str(metadata.get("published_at") or utc_now_iso())
    metadata["mandatory"] = bool(metadata.get("mandatory"))
    metadata["minimum_supported_version"] = str(
        metadata.get("minimum_supported_version") or (metadata["version"] if metadata["mandatory"] else "0.0.0")
    )
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    metadata["files"] = {
        str(platform): normalize_file_entry(entry)
        for platform, entry in files.items()
        if isinstance(entry, dict)
    }
    resolved = _with_resolved_download(metadata, None)
    _write_json(LATEST_METADATA_PATH, resolved)
    if append_history:
        append_version_history(resolved)
    _sync_update_feed_files(resolved)
    return resolved


def normalize_file_entry(entry: Dict[str, object]) -> Dict[str, object]:
    filename = str(entry.get("filename") or entry.get("name") or "").strip()
    platform = str(entry.get("platform") or "").strip()
    return {
        "platform": platform,
        "filename": filename,
        "download_url": str(entry.get("download_url") or (f"/updates/download/{quote(filename)}" if filename else "")).strip(),
        "size": int(entry.get("size") or 0),
        "sha512": str(entry.get("sha512") or "").strip(),
        "content_type": str(entry.get("content_type") or "application/octet-stream").strip(),
        "uploaded_at": str(entry.get("uploaded_at") or utc_now_iso()),
    }


def _resolve_platform_entry(metadata: Dict[str, object], platform: Optional[str]) -> Tuple[str, Dict[str, object]]:
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    requested = str(platform or "").strip().lower()
    if requested in files:
        return requested, dict(files[requested])
    if requested == "windows" and "win32" in files:
        return "win32", dict(files["win32"])
    if requested == "macos" and "darwin" in files:
        return "darwin", dict(files["darwin"])
    if requested == "appimage" and "linux" in files:
        return "linux", dict(files["linux"])
    if files:
        first_platform = sorted(files.keys())[0]
        return first_platform, dict(files[first_platform])
    return "", {}


def _with_resolved_download(metadata: Dict[str, object], platform: Optional[str]) -> Dict[str, object]:
    platform_key, file_entry = _resolve_platform_entry(metadata, platform)
    return {
        **metadata,
        "platform": platform_key,
        "download_url": str(file_entry.get("download_url") or metadata.get("download_url") or ""),
        "download_name": str(file_entry.get("filename") or metadata.get("download_name") or ""),
        "download_size": int(file_entry.get("size") or metadata.get("download_size") or 0),
        "sha512": str(file_entry.get("sha512") or metadata.get("sha512") or ""),
        "available_platforms": sorted((metadata.get("files") or {}).keys()),
    }


def build_latest_response(*, current_version: Optional[str] = None, platform: Optional[str] = None) -> Dict[str, object]:
    metadata = _with_resolved_download(load_latest_metadata(), platform)
    if not current_version:
        return metadata
    current = str(current_version or "").strip() or "0.0.0"
    latest = str(metadata.get("version") or "0.0.0")
    mandatory = bool(metadata.get("mandatory"))
    minimum_supported = str(metadata.get("minimum_supported_version") or (latest if mandatory else "0.0.0"))
    update_available = semver_key(current) < semver_key(latest)
    return {
        **metadata,
        "current_version": current,
        "latest_version": latest,
        "update_available": update_available,
        "has_update": update_available,
        "is_supported": semver_key(current) >= semver_key(minimum_supported),
        "mandatory": mandatory,
        "release_notes": str(metadata.get("release_notes") or ""),
    }


def read_version_history() -> List[Dict[str, object]]:
    ensure_update_storage()
    payload = _read_json(VERSION_HISTORY_PATH, [])
    if not isinstance(payload, list):
        return []
    history = [item for item in payload if isinstance(item, dict)]
    history.sort(key=lambda item: semver_key(str(item.get("version") or "0.0.0")), reverse=True)
    return history


def append_version_history(metadata: Dict[str, object]) -> List[Dict[str, object]]:
    history = read_version_history()
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    entry = {
        "version": str(metadata.get("version") or ""),
        "date": str(metadata.get("release_date") or ""),
        "notes": str(metadata.get("release_notes") or ""),
        "mandatory": bool(metadata.get("mandatory")),
        "minimum_supported_version": str(metadata.get("minimum_supported_version") or "0.0.0"),
        "published_at": str(metadata.get("published_at") or utc_now_iso()),
        "platforms": sorted(files.keys()),
        "files": files,
    }
    history = [item for item in history if str(item.get("version") or "") != entry["version"]]
    history.insert(0, entry)
    _write_json(VERSION_HISTORY_PATH, history)
    return history


def decode_data_url(data_url: str) -> Tuple[bytes, str]:
    match = DATA_URL_RE.match(str(data_url or "").strip())
    if not match:
        raise ValueError("Update upload must be a base64 data URL.")
    try:
        return base64.b64decode(match.group("data")), str(match.group("mime") or "application/octet-stream")
    except Exception as exc:
        raise ValueError("Invalid base64 update payload.") from exc


def publish_update(
    *,
    version: str,
    release_notes: str,
    mandatory: bool,
    filename: str,
    file_data: str,
    release_date: Optional[str] = None,
) -> Dict[str, object]:
    ensure_update_storage()
    normalized_version = str(version or "").strip()
    if not SEMVER_RE.match(normalized_version):
        raise ValueError("Version must use semantic versioning, for example 1.1.0")
    safe_name = Path(str(filename or "").strip()).name
    if not safe_name:
        raise ValueError("Installer filename is required.")
    platform = infer_platform_from_filename(safe_name)
    content, content_type = decode_data_url(file_data)
    if len(content) > MAX_UPDATE_SIZE_BYTES:
        raise ValueError("Update file exceeds the 500MB limit.")
    suffix = Path(safe_name).suffix
    normalized_filename = f"desktop-{normalized_version}{suffix}"
    file_path = UPDATE_FILES_DIR / normalized_filename
    file_path.write_bytes(content)
    sha512 = base64.b64encode(hashlib.sha512(content).digest()).decode("ascii")
    current = load_latest_metadata()
    same_version = str(current.get("version") or "") == normalized_version
    files = dict(current.get("files") or {}) if same_version else {}
    files[platform] = normalize_file_entry(
        {
            "platform": platform,
            "filename": normalized_filename,
            "download_url": f"/updates/download/{quote(normalized_filename)}",
            "size": len(content),
            "sha512": sha512,
            "content_type": content_type,
            "uploaded_at": utc_now_iso(),
        }
    )
    metadata = save_latest_metadata(
        {
            "version": normalized_version,
            "release_date": str(release_date or date.today().isoformat()),
            "release_notes": str(release_notes or "").strip(),
            "mandatory": bool(mandatory),
            "minimum_supported_version": normalized_version if mandatory else "0.0.0",
            "files": files,
            "published_at": utc_now_iso(),
        },
        append_history=True,
    )
    return _with_resolved_download(metadata, platform)


def get_download_path(filename: str) -> Path:
    safe_name = Path(str(filename or "").strip()).name
    if not safe_name:
        raise ValueError("Filename is required.")
    path = UPDATE_FILES_DIR / safe_name
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(safe_name)
    return path


def get_release_snapshot(*, platform: Optional[str] = None) -> Dict[str, object]:
    metadata = _with_resolved_download(load_latest_metadata(), platform)
    latest_version = str(metadata.get("version") or "0.1.0")
    return {
        "latest_version": latest_version,
        "minimum_supported_version": str(metadata.get("minimum_supported_version") or ("0.0.0" if not metadata.get("mandatory") else latest_version)),
        "download_url": str(metadata.get("download_url") or ""),
        "release_notes": str(metadata.get("release_notes") or ""),
        "mandatory": bool(metadata.get("mandatory")),
        "published_at": str(metadata.get("published_at") or ""),
        "release_date": str(metadata.get("release_date") or ""),
        "platform": str(metadata.get("platform") or ""),
    }


def save_release_snapshot(payload: Dict[str, object]) -> Dict[str, object]:
    existing = load_latest_metadata()
    version = str(payload.get("latest_version") or payload.get("version") or existing.get("version") or "0.1.0").strip()
    metadata = save_latest_metadata(
        {
            **existing,
            "version": version,
            "release_date": str(payload.get("release_date") or existing.get("release_date") or date.today().isoformat()),
            "release_notes": str(payload.get("release_notes") or existing.get("release_notes") or ""),
            "mandatory": bool(payload.get("mandatory", False)),
            "minimum_supported_version": str(
                payload.get("minimum_supported_version") or (version if payload.get("mandatory") else "0.0.0")
            ),
            "download_url": str(payload.get("download_url") or existing.get("download_url") or ""),
            "published_at": str(payload.get("published_at") or utc_now_iso()),
            "files": dict(existing.get("files") or {}),
        }
    )
    return get_release_snapshot(platform=metadata.get("platform"))


def _sync_update_feed_files(metadata: Dict[str, object]) -> None:
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    _write_feed_file(LATEST_WINDOWS_YML_PATH, metadata, files.get("win32"))
    _write_feed_file(LATEST_MAC_YML_PATH, metadata, files.get("darwin"))
    _write_feed_file(LATEST_LINUX_YML_PATH, metadata, files.get("linux"))


def _write_feed_file(path: Path, metadata: Dict[str, object], file_entry: Optional[Dict[str, object]]) -> None:
    if not file_entry:
        if path.exists():
            path.unlink()
        return
    version = str(metadata.get("version") or "0.1.0")
    escaped_notes = json.dumps(str(metadata.get("release_notes") or ""))
    release_date = str(metadata.get("published_at") or utc_now_iso())
    filename = str(file_entry.get("filename") or "")
    sha512 = str(file_entry.get("sha512") or "")
    size = int(file_entry.get("size") or 0)
    content = "\n".join(
        [
            f"version: {version}",
            f"path: download/{filename}",
            f"sha512: {sha512}",
            f"releaseDate: '{release_date}'",
            "files:",
            f"  - url: download/{filename}",
            f"    sha512: {sha512}",
            f"    size: {size}",
            f"releaseNotes: {escaped_notes}",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
