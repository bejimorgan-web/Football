import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app_storage


def test_apply_local_snapshot_restores_tracked_files(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    local_storage = tmp_path / "app_storage.json"
    monkeypatch.setattr(app_storage, "APP_STORAGE_PATH", local_storage)
    monkeypatch.setattr(app_storage, "_BOOTSTRAP_DONE", False)

    snapshot = {
        "version": 1,
        "files": {
            "master/providers.json": [{"provider_id": "active", "name": "Primary"}],
            "tenants/client-1/approved_streams.json": [{"stream_id": "123"}],
            "tenants/client-1/football_metadata.json": {"nations": [], "competitions": [], "clubs": []},
        },
    }
    local_storage.write_text(json.dumps(snapshot), encoding="utf-8")

    app_storage.ensure_app_storage_loaded(data_dir=data_dir)

    assert json.loads((data_dir / "master" / "providers.json").read_text(encoding="utf-8"))[0]["name"] == "Primary"
    assert json.loads((data_dir / "tenants" / "client-1" / "approved_streams.json").read_text(encoding="utf-8"))[0]["stream_id"] == "123"


def test_fetches_snapshot_from_github_when_local_file_is_missing(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    local_storage = tmp_path / "app_storage.json"
    monkeypatch.setattr(app_storage, "APP_STORAGE_PATH", local_storage)
    monkeypatch.setattr(app_storage, "_BOOTSTRAP_DONE", False)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    monkeypatch.setenv("GITHUB_BRANCH", "main")

    remote_snapshot = {
        "version": 1,
        "files": {
            "master/channels.json": [{"channel_id": "c1"}],
        },
    }

    def fake_request(url, *, method="GET", payload=None):
        assert method == "GET"
        return {
            "content": base64.b64encode(json.dumps(remote_snapshot).encode("utf-8")).decode("utf-8"),
        }

    monkeypatch.setattr(app_storage, "_github_request", fake_request)

    app_storage.ensure_app_storage_loaded(data_dir=data_dir)

    assert local_storage.exists()
    assert json.loads((data_dir / "master" / "channels.json").read_text(encoding="utf-8"))[0]["channel_id"] == "c1"


def test_persist_builds_local_snapshot_and_pushes_to_github(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    tracked_file = data_dir / "master" / "providers.json"
    tracked_file.parent.mkdir(parents=True, exist_ok=True)
    tracked_file.write_text(json.dumps([{"provider_id": "active"}]), encoding="utf-8")

    local_storage = tmp_path / "app_storage.json"
    monkeypatch.setattr(app_storage, "APP_STORAGE_PATH", local_storage)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    monkeypatch.setenv("GITHUB_BRANCH", "main")

    pushed = {}

    def fake_request(url, *, method="GET", payload=None):
        if method == "GET":
            return {"sha": "existing-sha"}
        pushed["url"] = url
        pushed["payload"] = payload
        return {}

    monkeypatch.setattr(app_storage, "_github_request", fake_request)

    app_storage.persist_app_storage_for_path(tracked_file, data_dir=data_dir)

    local_payload = json.loads(local_storage.read_text(encoding="utf-8"))
    assert "master/providers.json" in local_payload["files"]
    assert pushed["payload"]["message"] == "update app storage"
    assert pushed["payload"]["sha"] == "existing-sha"
