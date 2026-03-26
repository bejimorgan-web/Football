from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import require_role
from app.routes.football_data import get_fixtures, get_live_scores, get_standings
from app.storage import delete_club, delete_competition, delete_nation, upsert_club, upsert_competition, upsert_nation

router = APIRouter(prefix="/football", tags=["football"])


class FootballCatalogPayload(BaseModel):
    entity_type: str
    name: str
    nation_id: Optional[str] = None
    competition_id: Optional[str] = None
    competition_type: Optional[str] = "league"
    logo_url: Optional[str] = ""


@router.get("/live")
async def football_live():
    return await get_live_scores()


@router.get("/fixtures")
async def football_fixtures(competition_code: str = Query("PL")):
    return await get_fixtures(competition_code)


@router.get("/standings")
async def football_standings(competition_code: str = Query("PL")):
    return await get_standings(competition_code)


@router.put("/{item_id}")
def update_football_item(item_id: str, payload: FootballCatalogPayload, tenant_id: Optional[str] = Query(None), _: dict = Depends(require_role("master", "client"))):
    try:
        entity_type = str(payload.entity_type or "").strip().lower()
        scoped_tenant_id = str(tenant_id or "default").strip() or "default"
        if entity_type == "nation":
            item = upsert_nation(
                nation_id=item_id,
                name=payload.name,
                logo_url=payload.logo_url or "",
                tenant_id=scoped_tenant_id,
            )
        elif entity_type == "competition":
            item = upsert_competition(
                competition_id=item_id,
                nation_id=payload.nation_id,
                name=payload.name,
                type=payload.competition_type or "league",
                logo_url=payload.logo_url or "",
                tenant_id=scoped_tenant_id,
            )
        elif entity_type == "club":
            item = upsert_club(
                club_id=item_id,
                nation_id=payload.nation_id,
                competition_id=payload.competition_id,
                name=payload.name,
                logo_url=payload.logo_url or "",
                tenant_id=scoped_tenant_id,
            )
        else:
            raise ValueError("entity_type must be nation, competition, or club.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/{item_id}")
def delete_football_item(item_id: str, entity_type: str = Query(...), tenant_id: Optional[str] = Query(None), _: dict = Depends(require_role("master", "client"))):
    try:
        normalized_type = str(entity_type or "").strip().lower()
        scoped_tenant_id = str(tenant_id or "default").strip() or "default"
        if normalized_type == "nation":
            delete_nation(item_id, tenant_id=scoped_tenant_id)
        elif normalized_type == "competition":
            delete_competition(item_id, tenant_id=scoped_tenant_id)
        elif normalized_type == "club":
            delete_club(item_id, tenant_id=scoped_tenant_id)
        else:
            raise ValueError("entity_type must be nation, competition, or club.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "id": item_id, "entity_type": normalized_type}
