from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.auth import SINGLE_TENANT_ID
from app.api_config import get_api_base_url
from app.server_config import load_server_config
from app.storage import get_branding_config

router = APIRouter()


def _public_branding_payload(payload: dict) -> dict:
    branding = payload.get("branding") if isinstance(payload.get("branding"), dict) else {}
    logo_url = str(branding.get("logo_url") or branding.get("logo_file") or "").strip()
    return {
        "branding": {
            "app_name": str(branding.get("app_name") or payload.get("name") or "").strip(),
            "logo_url": logo_url,
            "primary_color": str(branding.get("primary_color") or "").strip(),
            "secondary_color": str(branding.get("secondary_color") or branding.get("accent_color") or "").strip(),
            "accent_color": str(branding.get("accent_color") or branding.get("secondary_color") or "").strip(),
            "surface_color": str(branding.get("surface_color") or "").strip(),
            "background_color": str(branding.get("background_color") or "").strip(),
            "text_color": str(branding.get("text_color") or "").strip(),
            "splash_screen": str(branding.get("splash_screen") or "").strip(),
        }
    }


@router.get("")
def server_config():
    server_urls = load_server_config()
    api_base_url = get_api_base_url()
    return {
        "public_url": server_urls["public_url"],
        "local_url": server_urls["local_url"],
        "api_base_url": api_base_url,
        "endpoints": {
            "version": f"{api_base_url}/api/version",
            "streams": f"{api_base_url}/streams",
            "analytics": f"{api_base_url}/analytics",
            "football_live": f"{api_base_url}/football/live",
        },
    }


@router.get("/branding")
def branding_config(tenant_id: Optional[str] = Query(None)):
    try:
        return _public_branding_payload(get_branding_config(SINGLE_TENANT_ID))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
