from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app import sources_store
from app.routes import sources as sources_route


def test_sources_crud_and_stream_fetch(monkeypatch, tmp_path: Path):
    sources_path = tmp_path / "sources.json"
    monkeypatch.setattr(sources_store, "SOURCES_PATH", sources_path)
    monkeypatch.setattr(
        sources_route,
        "list_streams",
        lambda settings, force_refresh=False: [
            {"id": "1", "name": "Sports One", "url": "http://example.test/live/1.m3u8", "group": "Sports"},
            {"id": "2", "name": "Sports Two", "url": "http://example.test/live/2.m3u8", "group": "Sports"},
        ],
    )

    client = TestClient(app)

    list_response = client.get("/sources")
    assert list_response.status_code == 200
    assert list_response.json() == {"items": []}

    create_response = client.post(
        "/sources",
        json={
            "name": "Primary Xtream",
            "type": "xtream",
            "url": "http://iptv.example.test",
            "username": "alice",
            "password": "secret",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()["item"]
    assert created["name"] == "Primary Xtream"
    assert created["type"] == "xtream"
    assert created["url"] == "http://iptv.example.test"
    assert created["username"] == "alice"
    assert created["password"] == "secret"
    assert created["id"]

    streams_response = client.get(f"/sources/{created['id']}/streams")
    assert streams_response.status_code == 200
    streams_payload = streams_response.json()
    assert streams_payload["source"]["id"] == created["id"]
    assert streams_payload["total"] == 2
    assert streams_payload["items"][0]["name"] == "Sports One"

    delete_response = client.delete(f"/sources/{created['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert delete_response.json()["items"] == []
