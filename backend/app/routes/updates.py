from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app.auth import require_role
from app.update_service import (
    LATEST_LINUX_YML_PATH,
    LATEST_MAC_YML_PATH,
    LATEST_WINDOWS_YML_PATH,
    build_latest_response,
    ensure_update_storage,
    get_download_path,
    load_latest_metadata,
    publish_update,
    read_version_history,
)

router = APIRouter()
MASTER_ACCESS = Depends(require_role("master"))


class UpdatePublishPayload(BaseModel):
    version: str
    filename: str
    file_data: str
    release_notes: str = ""
    mandatory: bool = False
    release_date: Optional[str] = None


@router.get("/latest")
def get_latest_update(
    current_version: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None),
):
    ensure_update_storage()
    return build_latest_response(current_version=current_version, platform=platform)


@router.get("/history")
def get_update_history():
    ensure_update_storage()
    return read_version_history()


@router.get("/download/{filename}")
def download_update_file(filename: str):
    try:
        file_path = get_download_path(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Update file not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path=file_path, filename=file_path.name, media_type="application/octet-stream")


@router.get("/files/{filename}")
def get_update_file_alias(filename: str):
    return download_update_file(filename)


@router.get("/latest.yml", response_class=PlainTextResponse)
def get_windows_feed():
    ensure_update_storage()
    if not LATEST_WINDOWS_YML_PATH.exists():
        raise HTTPException(status_code=404, detail="Windows update feed not available.")
    return PlainTextResponse(LATEST_WINDOWS_YML_PATH.read_text(encoding="utf-8"), media_type="text/yaml")


@router.get("/latest-mac.yml", response_class=PlainTextResponse)
def get_mac_feed():
    ensure_update_storage()
    if not LATEST_MAC_YML_PATH.exists():
        raise HTTPException(status_code=404, detail="macOS update feed not available.")
    return PlainTextResponse(LATEST_MAC_YML_PATH.read_text(encoding="utf-8"), media_type="text/yaml")


@router.get("/latest-linux.yml", response_class=PlainTextResponse)
def get_linux_feed():
    ensure_update_storage()
    if not LATEST_LINUX_YML_PATH.exists():
        raise HTTPException(status_code=404, detail="Linux update feed not available.")
    return PlainTextResponse(LATEST_LINUX_YML_PATH.read_text(encoding="utf-8"), media_type="text/yaml")


@router.post("/publish")
def publish_desktop_update(payload: UpdatePublishPayload, _: dict = MASTER_ACCESS):
    try:
        metadata = publish_update(
            version=payload.version,
            filename=payload.filename,
            file_data=payload.file_data,
            release_notes=payload.release_notes,
            mandatory=payload.mandatory,
            release_date=payload.release_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "published",
        "latest": metadata,
        "history": read_version_history(),
    }


@router.get("/manifest")
def get_raw_manifest():
    ensure_update_storage()
    return load_latest_metadata()
