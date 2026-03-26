import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import storage, update_service
from app.routes.admin import router as admin_router
from app.routes.admin_auth import router as admin_auth_router
from app.routes.updates import router as updates_router
from app.routes.version import router as version_router


def _configure_temp_storage(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    backend_root = tmp_path / "backend_root"
    updates_dir = backend_root / "updates"
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
    monkeypatch.setattr(storage, "APK_VERSIONS_PATH", data_dir / "apk_versions.json")
    monkeypatch.setattr(storage, "APP_DOWNLOADS_DIR", backend_root / "app" / "downloads")
    monkeypatch.setattr(update_service, "BASE_DIR", backend_root)
    monkeypatch.setattr(update_service, "UPDATES_DIR", updates_dir)
    monkeypatch.setattr(update_service, "UPDATE_FILES_DIR", updates_dir / "files")
    monkeypatch.setattr(update_service, "LATEST_METADATA_PATH", updates_dir / "latest.json")
    monkeypatch.setattr(update_service, "VERSION_HISTORY_PATH", updates_dir / "versions.json")
    monkeypatch.setattr(update_service, "LATEST_WINDOWS_YML_PATH", updates_dir / "latest.yml")
    monkeypatch.setattr(update_service, "LATEST_MAC_YML_PATH", updates_dir / "latest-mac.yml")
    monkeypatch.setattr(update_service, "LATEST_LINUX_YML_PATH", updates_dir / "latest-linux.yml")
    storage._ACTIVE_VIEWERS.clear()
    storage.ensure_storage_files()
    update_service.ensure_update_storage()


def _app():
    app = FastAPI()
    app.include_router(admin_auth_router, prefix="/admin/auth")
    app.include_router(admin_router, prefix="/admin")
    app.include_router(updates_router, prefix="/updates")
    app.include_router(version_router)
    return app


def _master_headers(client: TestClient):
    created = storage.register_admin(
        name="Master Admin",
        email="master@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-master",
    )
    binding = client.post(
        "/admin/register-server",
        json={
            "api_token": created["api_token"],
            "device_id": "desktop-master",
            "server_domain": "master-host",
            "server_ip": "10.0.0.5",
            "hardware_hash": "hw-master",
        },
        headers={"Authorization": f"Bearer {created['api_token']}", "X-Device-Id": "desktop-master"},
    )
    assert binding.status_code == 200
    server_id = binding.json()["admin"]["server_id"]
    return {
        "Authorization": f"Bearer {created['api_token']}",
        "X-Device-Id": "desktop-master",
        "X-Server-Id": server_id,
    }


def test_updates_latest_and_history_defaults(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    client = TestClient(_app())

    latest = client.get("/updates/latest")
    history = client.get("/updates/history")

    assert latest.status_code == 200
    assert latest.json()["version"] == "0.1.0"
    assert history.status_code == 200
    assert history.json()[0]["version"] == "0.1.0"


def test_master_can_publish_update_and_download(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    client = TestClient(_app())
    headers = _master_headers(client)
    content = b"fake-installer-content"
    data_url = f"data:application/octet-stream;base64,{base64.b64encode(content).decode('ascii')}"

    published = client.post(
        "/updates/publish",
        json={
            "version": "1.1.0",
            "filename": "desktop-1.1.0.exe",
            "file_data": data_url,
            "release_notes": "Improved stream approval panel and analytics performance",
            "mandatory": True,
            "release_date": "2026-03-25",
        },
        headers=headers,
    )

    assert published.status_code == 200
    latest = client.get("/updates/latest", params={"current_version": "1.0.0", "platform": "win32"})
    assert latest.status_code == 200
    body = latest.json()
    assert body["update_available"] is True
    assert body["latest_version"] == "1.1.0"
    assert body["mandatory"] is True
    assert body["download_url"].endswith("/updates/download/desktop-1.1.0.exe")

    download = client.get("/updates/download/desktop-1.1.0.exe")
    assert download.status_code == 200
    assert download.content == content

    feed = client.get("/updates/latest.yml")
    assert feed.status_code == 200
    assert "desktop-1.1.0.exe" in feed.text


def test_client_cannot_publish_update(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    client = TestClient(_app())
    master_headers = _master_headers(client)
    client_admin = storage.register_admin(
        name="Client Admin",
        email="client@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-client",
    )
    client_bind = client.post(
        "/admin/register-server",
        json={
            "api_token": client_admin["api_token"],
            "device_id": "desktop-client",
            "server_domain": "tenant-host",
            "server_ip": "10.0.0.6",
            "hardware_hash": "hw-client",
        },
        headers={"Authorization": f"Bearer {client_admin['api_token']}", "X-Device-Id": "desktop-client"},
    )
    assert client_bind.status_code == 200
    server_id = client_bind.json()["admin"]["server_id"]
    client_headers = {
        "Authorization": f"Bearer {client_admin['api_token']}",
        "X-Device-Id": "desktop-client",
        "X-Server-Id": server_id,
    }
    data_url = "data:application/octet-stream;base64,ZmFrZQ=="

    forbidden = client.post(
        "/updates/publish",
        json={
            "version": "1.2.0",
            "filename": "desktop-1.2.0.exe",
            "file_data": data_url,
            "release_notes": "Forbidden publish attempt",
            "mandatory": False,
        },
        headers=client_headers,
    )

    assert forbidden.status_code == 403

    allowed = client.post(
        "/updates/publish",
        json={
            "version": "1.2.0",
            "filename": "desktop-1.2.0.exe",
            "file_data": data_url,
            "release_notes": "Master publish",
            "mandatory": False,
        },
        headers=master_headers,
    )
    assert allowed.status_code == 200


def test_publish_validates_extension(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    client = TestClient(_app())
    headers = _master_headers(client)

    invalid = client.post(
        "/updates/publish",
        json={
            "version": "1.1.0",
            "filename": "desktop-1.1.0.zip",
            "file_data": "data:application/zip;base64,ZmFrZQ==",
            "release_notes": "Invalid format",
            "mandatory": False,
        },
        headers=headers,
    )

    assert invalid.status_code == 400
    assert "Unsupported update file type" in invalid.json()["detail"]


def test_api_version_exposes_desktop_and_mobile_manifest(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    client = TestClient(_app())
    headers = _master_headers(client)
    published = client.post(
        "/updates/publish",
        json={
            "version": "2.0.0",
            "filename": "desktop-2.0.0.exe",
            "file_data": "data:application/octet-stream;base64,ZmFrZQ==",
            "release_notes": "Major release",
            "mandatory": True,
        },
        headers=headers,
    )
    assert published.status_code == 200

    version_response = client.get(
        "/api/version",
        params={"tenant_id": "master", "current_version": "1.0.0", "platform": "win32", "client": "mobile"},
    )

    assert version_response.status_code == 200
    payload = version_response.json()
    assert payload["desktop"]["latest_version"] == "2.0.0"
    assert payload["desktop"]["has_update"] is True
    assert payload["mobile"]["feature_flags"]["live_scores"] is True
    assert payload["mobile"]["language"]["default"] == "system"


def test_master_can_upload_and_set_latest_apk(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    client = TestClient(_app())
    headers = _master_headers(client)
    first_apk = "data:application/vnd.android.package-archive;base64,Zmlyc3Q="
    second_apk = "data:application/vnd.android.package-archive;base64,c2Vjb25k"

    uploaded = client.post(
        "/admin/upload-apk",
        json={
            "version": "0.2.0",
            "filename": "release.apk",
            "file_data": first_apk,
        },
        headers=headers,
    )

    assert uploaded.status_code == 200
    first_item = uploaded.json()["item"]
    assert first_item["version"] == "0.2.0"
    assert first_item["file_path"] == "/downloads/app-v0.2.0.apk"

    uploaded_second = client.post(
        "/admin/upload-apk",
        json={
            "version": "0.3.0",
            "filename": "release-v3.apk",
            "file_data": second_apk,
        },
        headers=headers,
    )
    assert uploaded_second.status_code == 200
    second_item = uploaded_second.json()["item"]

    promoted = client.post(
        f"/admin/apk-versions/{second_item['id']}/set-latest",
        json={"force_update": True},
        headers=headers,
    )
    assert promoted.status_code == 200
    assert promoted.json()["item"]["is_latest"] is True
    assert promoted.json()["item"]["force_update"] is True

    latest_version = client.get(
        "/api/version",
        params={"tenant_id": "master", "current_version": "0.2.0", "platform": "android", "client": "mobile"},
    )
    assert latest_version.status_code == 200
    payload = latest_version.json()
    assert payload["latest_version"] == "0.3.0"
    assert payload["update_url"] == "/downloads/app-v0.3.0.apk"
    assert payload["force_update"] is True
    assert payload["mobile"]["update_url"] == "/downloads/app-v0.3.0.apk"


def test_client_cannot_upload_apk(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    client = TestClient(_app())
    client_admin = storage.register_admin(
        name="Client Admin",
        email="client-apk@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-client-apk",
    )
    client_bind = client.post(
        "/admin/register-server",
        json={
            "api_token": client_admin["api_token"],
            "device_id": "desktop-client-apk",
            "server_domain": "tenant-host",
            "server_ip": "10.0.0.6",
            "hardware_hash": "hw-client",
        },
        headers={"Authorization": f"Bearer {client_admin['api_token']}", "X-Device-Id": "desktop-client-apk"},
    )
    assert client_bind.status_code == 200
    server_id = client_bind.json()["admin"]["server_id"]
    client_headers = {
        "Authorization": f"Bearer {client_admin['api_token']}",
        "X-Device-Id": "desktop-client-apk",
        "X-Server-Id": server_id,
    }

    forbidden = client.post(
        "/admin/upload-apk",
        json={
            "version": "0.2.0",
            "filename": "release.apk",
            "file_data": "data:application/vnd.android.package-archive;base64,ZmFrZQ==",
        },
        headers=client_headers,
    )

    assert forbidden.status_code == 403
