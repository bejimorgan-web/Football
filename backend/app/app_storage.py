from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

APP_ROOT = Path(__file__).resolve().parents[2]
APP_STORAGE_PATH = APP_ROOT / "app_storage.json"
_TRACKED_FILENAMES = {
    "providers.json",
    "provider_groups.json",
    "channels.json",
    "football_metadata.json",
    "approved_streams.json",
}
_BOOTSTRAP_DONE = False


def ensure_app_storage_loaded(*, data_dir: Path, logger: Optional[logging.Logger] = None) -> None:
    global _BOOTSTRAP_DONE
    if _BOOTSTRAP_DONE:
        return
    snapshot = _load_snapshot_from_local(logger=logger)
    if snapshot is None:
        snapshot = _fetch_snapshot_from_github(logger=logger)
        if snapshot is not None:
            _write_snapshot_to_local(snapshot, logger=logger)
    if snapshot is not None:
        _apply_snapshot(snapshot, data_dir=data_dir, logger=logger)
    _BOOTSTRAP_DONE = True


def persist_app_storage_for_path(path: Path, *, data_dir: Path, logger: Optional[logging.Logger] = None) -> None:
    tracked_relative_path = _tracked_relative_path(path, data_dir=data_dir)
    if tracked_relative_path is None:
        return
    snapshot = _build_snapshot(data_dir=data_dir)
    _write_snapshot_to_local(snapshot, logger=logger)
    _push_snapshot_to_github(snapshot, logger=logger)


def _load_snapshot_from_local(*, logger: Optional[logging.Logger] = None) -> Optional[Dict[str, Any]]:
    if not APP_STORAGE_PATH.exists():
        return None
    try:
        payload = json.loads(APP_STORAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if logger is not None:
            logger.warning("Failed to read local app_storage.json: %s", exc)
        return None
    return payload if isinstance(payload, dict) else None


def _write_snapshot_to_local(snapshot: Dict[str, Any], *, logger: Optional[logging.Logger] = None) -> None:
    try:
        APP_STORAGE_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except OSError as exc:
        if logger is not None:
            logger.warning("Failed to write local app_storage.json: %s", exc)


def _tracked_relative_path(path: Path, *, data_dir: Path) -> Optional[str]:
    if path.name not in _TRACKED_FILENAMES:
        return None
    try:
        relative = path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return None
    return relative.as_posix()


def _build_snapshot(*, data_dir: Path) -> Dict[str, Any]:
    files: Dict[str, Any] = {}
    if data_dir.exists():
        for file_path in data_dir.rglob("*.json"):
            relative = _tracked_relative_path(file_path, data_dir=data_dir)
            if relative is None or not file_path.exists():
                continue
            try:
                files[relative] = json.loads(file_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return {
        "version": 1,
        "files": files,
    }


def _apply_snapshot(snapshot: Dict[str, Any], *, data_dir: Path, logger: Optional[logging.Logger] = None) -> None:
    files = snapshot.get("files")
    if not isinstance(files, dict):
        return
    data_root = data_dir.resolve()
    for relative_path, payload in files.items():
        if not isinstance(relative_path, str):
            continue
        destination = (data_root / relative_path).resolve()
        try:
            destination.relative_to(data_root)
        except ValueError:
            continue
        if destination.name not in _TRACKED_FILENAMES:
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            if logger is not None:
                logger.warning("Failed to hydrate %s from app_storage.json: %s", destination, exc)


def _github_request(url: str, *, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "football-streaming-app-storage",
    }
    token = str(os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=10) as response:
        raw = response.read().decode("utf-8")
    decoded = json.loads(raw) if raw else {}
    return decoded if isinstance(decoded, dict) else {}


def _github_repo_settings() -> Optional[tuple[str, str]]:
    repo = str(os.getenv("GITHUB_REPO") or "").strip()
    branch = str(os.getenv("GITHUB_BRANCH") or "").strip()
    token = str(os.getenv("GITHUB_TOKEN") or "").strip()
    if not repo or not branch or not token:
        return None
    return repo, branch


def _github_contents_url(repo: str, branch: str) -> str:
    query = urlencode({"ref": branch})
    return f"https://api.github.com/repos/{repo}/contents/app_storage.json?{query}"


def _fetch_snapshot_from_github(*, logger: Optional[logging.Logger] = None) -> Optional[Dict[str, Any]]:
    settings = _github_repo_settings()
    if settings is None:
        return None
    repo, branch = settings
    try:
        payload = _github_request(_github_contents_url(repo, branch))
    except HTTPError as exc:
        if exc.code != 404 and logger is not None:
            logger.warning("Failed to fetch app_storage.json from GitHub: %s", exc)
        return None
    except (URLError, OSError, json.JSONDecodeError) as exc:
        if logger is not None:
            logger.warning("Failed to fetch app_storage.json from GitHub: %s", exc)
        return None
    content = str(payload.get("content") or "").strip()
    if not content:
        return None
    try:
        decoded = base64.b64decode(content.encode("utf-8")).decode("utf-8")
        snapshot = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        if logger is not None:
            logger.warning("Invalid GitHub app_storage.json payload: %s", exc)
        return None
    return snapshot if isinstance(snapshot, dict) else None


def _push_snapshot_to_github(snapshot: Dict[str, Any], *, logger: Optional[logging.Logger] = None) -> None:
    settings = _github_repo_settings()
    if settings is None:
        return
    repo, branch = settings
    sha = None
    try:
        current = _github_request(_github_contents_url(repo, branch))
        sha = str(current.get("sha") or "").strip() or None
    except HTTPError as exc:
        if exc.code != 404 and logger is not None:
            logger.warning("Failed to read GitHub app_storage.json metadata: %s", exc)
    except (URLError, OSError, json.JSONDecodeError) as exc:
        if logger is not None:
            logger.warning("Failed to read GitHub app_storage.json metadata: %s", exc)
        return
    body: Dict[str, Any] = {
        "message": "update app storage",
        "content": base64.b64encode(json.dumps(snapshot, indent=2).encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    try:
        _github_request(
            f"https://api.github.com/repos/{repo}/contents/app_storage.json",
            method="PUT",
            payload=body,
        )
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        if logger is not None:
            logger.warning("Failed to push app_storage.json to GitHub: %s", exc)
