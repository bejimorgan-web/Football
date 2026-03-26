from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.api_config import get_api_base_url
from app.server_config import load_server_config
from app.storage import get_branding_config

router = APIRouter()


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
        return get_branding_config(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
