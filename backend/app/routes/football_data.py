import os

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/football-data", tags=["football-data"])

API_BASE = "https://api.football-data.org/v4"
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

headers = {"X-Auth-Token": API_KEY}


@router.get("/competitions")
async def get_competitions():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/competitions", headers=headers)
        return resp.json()


@router.get("/fixtures/{competition_code}")
async def get_fixtures(competition_code: str):
    """Return upcoming fixtures for a competition."""
    async with httpx.AsyncClient() as client:
        url = f"{API_BASE}/competitions/{competition_code}/matches?status=SCHEDULED"
        resp = await client.get(url, headers=headers)
        return resp.json()


@router.get("/standings/{competition_code}")
async def get_standings(competition_code: str):
    """Return league table standings."""
    async with httpx.AsyncClient() as client:
        url = f"{API_BASE}/competitions/{competition_code}/standings"
        resp = await client.get(url, headers=headers)
        return resp.json()


@router.get("/live-scores")
async def get_live_scores():
    """Return live matches with current score."""
    async with httpx.AsyncClient() as client:
        url = f"{API_BASE}/matches?status=LIVE"
        resp = await client.get(url, headers=headers)
        return resp.json()
