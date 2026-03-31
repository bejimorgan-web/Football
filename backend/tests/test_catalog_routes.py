import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import storage  # noqa: E402
from app.main import app  # noqa: E402


def _configure_temp_storage(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "ASSETS_DIR", data_dir / "assets")
    monkeypatch.setattr(storage, "CONFIG_PATH", data_dir / "config.json")
    monkeypatch.setattr(storage, "METADATA_PATH", data_dir / "football_metadata.json")
    monkeypatch.setattr(storage, "APPROVED_STREAMS_PATH", data_dir / "approved_streams.json")
    monkeypatch.setattr(storage, "USERS_PATH", data_dir / "users.json")
    monkeypatch.setattr(storage, "VIEWERS_PATH", data_dir / "viewers.json")
    monkeypatch.setattr(storage, "SESSIONS_PATH", data_dir / "sessions.json")
    monkeypatch.setattr(storage, "SECURITY_LOGS_PATH", data_dir / "security_logs.json")
    monkeypatch.setattr(storage, "TENANTS_PATH", data_dir / "tenants.json")
    monkeypatch.setattr(storage, "ADMINS_PATH", data_dir / "admins.json")
    monkeypatch.setattr(storage, "TENANT_DATA_DIR", data_dir / "tenants")
    monkeypatch.setattr(storage, "INSTALL_LOGS_PATH", data_dir / "install_logs.json")
    monkeypatch.setattr(storage, "SUBSCRIPTION_LOGS_PATH", data_dir / "subscription_logs.json")
    monkeypatch.setattr(storage, "AUDIT_LOGS_PATH", data_dir / "audit_logs.json")
    monkeypatch.setattr(storage, "EMAIL_LOGS_PATH", data_dir / "email_logs.json")
    monkeypatch.setattr(storage, "RELEASE_INFO_PATH", data_dir / "app_release.json")
    monkeypatch.setattr(storage, "LICENSES_PATH", data_dir / "licenses.json")
    monkeypatch.setattr(storage, "MASTER_DATA_DIR", data_dir / "master")
    storage._ACTIVE_VIEWERS.clear()
    storage.ensure_storage_files()


def test_catalog_routes_create_and_filter_entities(monkeypatch, tmp_path: Path) -> None:
    _configure_temp_storage(monkeypatch, tmp_path)
    client = TestClient(app)

    nation_response = client.post(
        "/nations",
        json={"id": "fr", "name": "France", "logo": "https://cdn.example.test/flags/fr.png"},
    )
    assert nation_response.status_code == 200
    nation = nation_response.json()["item"]
    assert nation == {
        "id": "fr",
        "name": "France",
        "logo": "https://cdn.example.test/flags/fr.png",
    }

    competition_response = client.post(
        "/competitions",
        json={
            "id": "ligue-1",
            "name": "Ligue 1",
            "nation_id": "fr",
            "logo": "https://cdn.example.test/competitions/ligue1.png",
            "type": "league",
        },
    )
    assert competition_response.status_code == 200
    competition = competition_response.json()["item"]
    assert competition["id"] == "ligue-1"
    assert competition["nation_id"] == "fr"
    assert competition["logo"] == "https://cdn.example.test/competitions/ligue1.png"

    club_response = client.post(
        "/clubs",
        json={
            "id": "psg",
            "name": "Paris Saint-Germain",
            "competition_id": "ligue-1",
            "logo": "https://cdn.example.test/clubs/psg.png",
        },
    )
    assert club_response.status_code == 200
    club = club_response.json()["item"]
    assert club["id"] == "psg"
    assert club["competition_id"] == "ligue-1"
    assert club["nation_id"] == "fr"
    assert club["logo"] == "https://cdn.example.test/clubs/psg.png"

    nations_response = client.get("/nations")
    assert nations_response.status_code == 200
    assert nations_response.json()["items"] == [nation]

    competitions_response = client.get("/competitions", params={"nation_id": "fr"})
    assert competitions_response.status_code == 200
    assert competitions_response.json()["items"] == [competition]

    clubs_response = client.get("/clubs", params={"competition_id": "ligue-1"})
    assert clubs_response.status_code == 200
    assert clubs_response.json()["items"] == [club]
