from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.storage import list_clubs, list_competitions, list_nations, upsert_club, upsert_competition, upsert_nation

router = APIRouter(tags=["catalog"])


class NationPayload(BaseModel):
    id: Optional[str] = None
    name: str
    logo: str = ""


class CompetitionPayload(BaseModel):
    id: Optional[str] = None
    name: str
    nation_id: str
    logo: str = ""
    type: str = "league"


class ClubPayload(BaseModel):
    id: Optional[str] = None
    name: str
    competition_id: str
    logo: str = ""


def _serialize_nation(item: dict) -> dict:
    return {"id": str(item.get("id") or ""), "name": str(item.get("name") or ""), "logo": str(item.get("logo_url") or "")}


def _serialize_competition(item: dict) -> dict:
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "logo": str(item.get("logo_url") or ""),
        "nation_id": str(item.get("nation_id") or ""),
        "type": str(item.get("type") or "league"),
    }


def _serialize_club(item: dict) -> dict:
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "logo": str(item.get("logo_url") or ""),
        "competition_id": str(item.get("competition_id") or ""),
        "nation_id": str(item.get("nation_id") or ""),
    }


@router.get("/nations")
def get_nations():
    return {"items": [_serialize_nation(item) for item in list_nations()]}


@router.post("/nations")
def create_nation(payload: NationPayload):
    try:
        item = upsert_nation(nation_id=payload.id, name=payload.name, logo_url=payload.logo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": _serialize_nation(item)}


@router.get("/competitions")
def get_competitions(nation_id: Optional[str] = Query(None)):
    return {"items": [_serialize_competition(item) for item in list_competitions(nation_id=nation_id)]}


@router.post("/competitions")
def create_competition(payload: CompetitionPayload):
    try:
        item = upsert_competition(
            competition_id=payload.id,
            name=payload.name,
            nation_id=payload.nation_id,
            competition_type=payload.type,
            logo_url=payload.logo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": _serialize_competition(item)}


@router.get("/clubs")
def get_clubs(competition_id: Optional[str] = Query(None), nation_id: Optional[str] = Query(None)):
    return {"items": [_serialize_club(item) for item in list_clubs(nation_id=nation_id, competition_id=competition_id)]}


@router.post("/clubs")
def create_club(payload: ClubPayload):
    competitions = list_competitions()
    competition = next((item for item in competitions if str(item.get("id") or "") == payload.competition_id), None)
    if competition is None:
        raise HTTPException(status_code=400, detail="Competition not found.")
    try:
        item = upsert_club(
            club_id=payload.id,
            name=payload.name,
            nation_id=str(competition.get("nation_id") or ""),
            competition_id=payload.competition_id,
            logo_url=payload.logo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": _serialize_club(item)}
