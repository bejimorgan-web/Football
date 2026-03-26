from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app.services.iptv import IPTVAuthError, IPTVProviderError, list_streams
from app.storage import load_config, resolve_playback_url, validate_stream_token

router = APIRouter()


def _require_settings():
    settings = load_config()
    if settings is None:
        raise HTTPException(status_code=503, detail="Backend is not configured.")
    return settings


@router.get("/play/{token}")
def play_stream(token: str):
    try:
        payload = validate_stream_token(token)
        settings = _require_settings()
        stream_url = resolve_playback_url(
            list_streams(settings=settings, force_refresh=False),
            str(payload.get("stream_id") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IPTVAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except IPTVProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RedirectResponse(url=stream_url, status_code=307)
