from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import require_admin_context
from app.routes.admin import router as admin_router
from app.routes.admin_auth import router as admin_auth_router
from app.routes.analytics import router as analytics_router
from app.routes.config import router as config_router
from app.routes.device import router as device_router
from app.routes.tenant import router as tenant_router
from app.routes.version import router as version_router
from app import storage


def _configure_temp_storage(monkeypatch, tmp_path):
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
    storage._ACTIVE_VIEWERS.clear()
    storage.ensure_storage_files()


def test_default_tenant_and_branding(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)

    tenant = storage.get_tenant("default")
    branding = storage.get_branding_config("default")

    assert tenant["tenant_id"] == "default"
    assert branding["branding"]["app_name"] == "Football Streaming"


def test_tenant_scoped_device_registration(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    storage.upsert_tenant(
        tenant_id="clubtv",
        name="Club TV",
        admin_username="club-admin",
        admin_password="secret",
        trial_policy={"enabled": True, "duration_days": 3},
    )

    device = storage.register_device(
        tenant_id="clubtv",
        device_id="device-1",
        device_name="Samsung A51",
        platform="android",
        app_version="1.0.0",
    )
    status = storage.get_device_status("device-1", tenant_id="clubtv", touch=False)

    assert device["tenant_id"] == "clubtv"
    assert status["tenant_id"] == "clubtv"
    assert status["status"] == "trial"


def test_tenant_login_and_profile_api(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    storage.upsert_tenant(
        tenant_id="clubtv",
        name="Club TV",
        admin_username="club-admin",
        admin_password="secret",
        branding={"app_name": "Club TV", "primary_color": "#FF5500"},
    )

    app = FastAPI()
    app.include_router(tenant_router, prefix="/tenant")
    app.include_router(config_router, prefix="/config")
    app.include_router(version_router)
    client = TestClient(app)

    login = client.post(
        "/tenant/login",
        json={"tenant_id": "clubtv", "username": "club-admin", "password": "secret"},
    )
    assert login.status_code == 200
    token = login.json()["token"]

    profile = client.get("/tenant/profile", headers={"Authorization": f"Bearer {token}"})
    branding = client.get("/config/branding?tenant_id=clubtv")

    assert profile.status_code == 200
    assert profile.json()["tenant"]["tenant_id"] == "clubtv"
    assert branding.status_code == 200
    assert branding.json()["branding"]["app_name"] == "Club TV"

    mobile_config = client.get("/tenant/mobile-config?tenant_id=clubtv")
    version_manifest = client.get("/api/version", params={"tenant_id": "clubtv", "client": "mobile"})

    assert mobile_config.status_code == 200
    assert mobile_config.json()["feature_flags"]["live_scores"] is False
    assert mobile_config.json()["language"]["supported"] == ["en", "fr"]
    assert version_manifest.status_code == 200
    assert version_manifest.json()["tenant_locked"] is True
    assert version_manifest.json()["mobile"]["feature_flags"]["core_feature_updates"] is False


def test_admin_auth_and_server_binding(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)

    app = FastAPI()
    app.include_router(admin_auth_router, prefix="/admin/auth")
    app.include_router(admin_router, prefix="/admin")
    client = TestClient(app)

    register = client.post(
        "/admin/auth/register",
        json={
            "name": "Studio Ops",
            "email": "ops@example.com",
            "password": "secret123",
            "plan_id": "trial",
            "device_id": "desktop-a",
        },
    )
    assert register.status_code == 200
    token = register.json()["api_token"]

    bind = client.post(
        "/admin/register-server",
        json={
            "api_token": token,
            "device_id": "desktop-a",
            "server_domain": "ops-host",
            "server_ip": "10.0.0.3",
            "hardware_hash": "hw-1",
        },
        headers={"Authorization": f"Bearer {token}", "X-Device-Id": "desktop-a"},
    )
    assert bind.status_code == 200
    server_id = bind.json()["admin"]["server_id"]

    blocked = client.get(
        "/analytics/live",
        headers={"Authorization": f"Bearer {token}", "X-Device-Id": "desktop-a", "X-Server-Id": "wrong-server"},
    )
    assert blocked.status_code == 401

    allowed = client.get(
        "/analytics/live",
        headers={"Authorization": f"Bearer {token}", "X-Device-Id": "desktop-a", "X-Server-Id": server_id},
    )
    assert allowed.status_code == 200


def test_admin_login_rejects_different_device(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    storage.register_admin(
        name="Desk Admin",
        email="desk@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-a",
    )

    app = FastAPI()
    app.include_router(admin_auth_router, prefix="/admin/auth")
    client = TestClient(app)

    login = client.post(
        "/admin/auth/login",
        json={
            "email": "desk@example.com",
            "password": "secret123",
            "device_id": "desktop-b",
        },
    )
    assert login.status_code == 401
    assert "bound to another desktop device" in login.json()["detail"]


def test_admin_renewal_reactivates_expired_subscription(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    created = storage.register_admin(
        name="Renew Admin",
        email="renew@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-a",
    )
    admin = storage.get_admin_by_email("renew@example.com")
    admin["subscription_end"] = "2000-01-01T00:00:00+00:00"
    admin["subscription_end_date"] = admin["subscription_end"]
    admin["subscription_status"] = "expired"
    admin["status"] = "inactive"
    storage.save_admins([admin])

    renewed = storage.renew_admin_subscription(
        api_token=created["api_token"],
        plan_id="1_year",
        payment_provider="stripe",
        payment_reference="invoice-001",
    )

    assert renewed["subscription_status"] == "active"
    assert renewed["status"] == "active"
    assert renewed["plan_id"] == "1_year"

    validated = storage.validate_admin_api_token(created["api_token"], device_id="desktop-a", require_server=False)
    assert validated["subscription_status"] == "active"


def test_admin_list_summaries_returns_branding(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    storage.register_admin(
        name="Brand Ops",
        email="brand@example.com",
        password="secret123",
        plan_id="6_months",
        device_id="desktop-a",
        payment_provider="paypal",
        payment_reference="txn-777",
    )

    items = storage.list_admin_summaries()

    assert len(items) == 1
    assert items[0]["email"] == "brand@example.com"
    assert items[0]["branding_info"]["app_name"] == "Brand Ops"


def test_admin_registration_creates_empty_tenant_files(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    created = storage.register_admin(
        name="Fresh Admin",
        email="fresh@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-a",
    )

    tenant_dir = storage.get_tenant_data_path(created["admin"]["admin_id"])

    assert tenant_dir.exists()
    assert storage._read_json(tenant_dir / "providers.json", None) == []
    assert storage._read_json(tenant_dir / "approved_streams.json", None) == []
    assert storage._read_json(tenant_dir / "football_metadata.json", None) == {"nations": [], "competitions": [], "clubs": []}
    assert storage._read_json(tenant_dir / "analytics.json", None) == []


def test_legacy_global_files_migrate_to_first_admin(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    storage._write_json(storage.DATA_DIR / "providers.json", [{"name": "Legacy Provider"}])
    storage._write_json(storage.APPROVED_STREAMS_PATH, [{"tenant_id": "default", "stream_id": "1"}])
    storage._write_json(storage.METADATA_PATH, {"nations": [{"id": "n1", "tenant_id": "default"}], "competitions": [], "clubs": []})

    created = storage.register_admin(
        name="Migrated Admin",
        email="migrate@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-a",
    )

    tenant_dir = storage.get_tenant_data_path(created["admin"]["admin_id"])

    assert storage._read_json(tenant_dir / "providers.json", None) == [{"name": "Legacy Provider"}]
    assert storage._read_json(tenant_dir / "approved_streams.json", None) == [{"tenant_id": "default", "stream_id": "1"}]
    assert storage._read_json(tenant_dir / "football_metadata.json", None)["nations"][0]["id"] == "n1"
    assert not (storage.DATA_DIR / "providers.json").exists()
    assert not storage.APPROVED_STREAMS_PATH.exists()
    assert not storage.METADATA_PATH.exists()


def test_mobile_tenant_validation_and_setup_meta(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    created = storage.register_admin(
        name="Mobile Admin",
        email="mobile@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-a",
    )
    bound = storage.register_admin_server(
        api_token=created["api_token"],
        device_id="desktop-a",
        server_domain="ops-host",
        server_ip="10.0.0.5",
        hardware_hash="hw-1",
    )

    meta = storage.get_setup_status(
        admin_id=created["admin"]["admin_id"],
        tenant_id=created["admin"]["tenant_id"],
    )
    assert meta["setup_completed"] is False
    assert meta["server_id"] == bound["server_id"]

    validated = storage.validate_mobile_tenant_access(
        api_token=meta["mobile_api_token"],
        tenant_id=created["admin"]["tenant_id"],
        device_id="desktop-a",
        server_id=bound["server_id"],
    )
    assert validated["tenant_id"] == created["admin"]["tenant_id"]

    completed = storage.mark_setup_completed(
        admin_id=created["admin"]["admin_id"],
        tenant_id=created["admin"]["tenant_id"],
    )
    assert completed["setup_completed"] is True


def test_install_and_subscription_tracking(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    created = storage.register_admin(
        name="Tracked Admin",
        email="tracked@example.com",
        password="secret123",
        plan_id="6_months",
        device_id="desktop-a",
    )

    install = storage.register_install_event(
        admin_id=created["admin"]["admin_id"],
        device_id="desktop-a",
        app_version="0.1.0",
        timestamp="2026-03-23T10:00:00+00:00",
    )
    subscription = storage.register_subscription_event(
        admin_id=created["admin"]["admin_id"],
        subscription_plan="6_months",
        start_date=created["admin"]["subscription_start_date"],
        end_date=created["admin"]["subscription_end_date"],
    )
    stats = storage.get_install_stats()

    assert install["device_id"] == "desktop-a"
    assert subscription["subscription_plan"] == "6_months"
    assert stats["totals"]["install_count"] == 1
    assert stats["totals"]["subscription_count"] == 1


def test_first_admin_is_master_and_next_is_client(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    first = storage.register_admin(
        name="Master Admin",
        email="master@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-master",
    )
    second = storage.register_admin(
        name="Tenant Admin",
        email="tenant@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-tenant",
    )

    assert first["admin"]["role"] == "master"
    assert second["admin"]["role"] == "client"
    assert first["admin"]["tenant_id"] == "master"
    assert second["admin"]["tenant_id"] != "master"


def test_master_uses_dedicated_storage_and_is_excluded_from_platform_client_lists(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    master = storage.register_admin(
        name="Master Admin",
        email="master@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-master",
    )
    client = storage.register_admin(
        name="Tenant Admin",
        email="tenant@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-tenant",
    )

    storage.save_provider_settings(
        storage.IPTVSettings(
            xtream_server_url="http://provider.example.com",
            xtream_username="master",
            xtream_password="secret",
            cache_ttl_seconds=300,
        ),
        admin_id=master["admin"]["admin_id"],
        tenant_id="master",
    )
    storage.save_provider_settings(
        storage.IPTVSettings(
            xtream_server_url="http://provider.example.com",
            xtream_username="tenant",
            xtream_password="secret",
            cache_ttl_seconds=300,
        ),
        admin_id=client["admin"]["admin_id"],
        tenant_id=client["admin"]["tenant_id"],
    )

    master_provider_path = storage.get_admin_storage_path(master["admin"]["admin_id"]) / "providers.json"
    tenant_provider_path = storage.get_admin_storage_path(client["admin"]["admin_id"]) / "providers.json"
    platform_clients = storage.list_platform_clients()
    platform_stats = storage.get_platform_client_stats()

    assert master_provider_path == storage.MASTER_DATA_DIR / "providers.json"
    assert tenant_provider_path == storage.TENANT_DATA_DIR / client["admin"]["admin_id"] / "providers.json"
    assert master_provider_path.exists()
    assert tenant_provider_path.exists()
    assert [item["admin_id"] for item in platform_clients] == [client["admin"]["admin_id"]]
    assert platform_stats["total_clients"] == 1


def test_master_login_does_not_require_license_key(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    storage.register_admin(
        name="Master Admin",
        email="master@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-master",
    )

    tenants = storage.load_tenants()
    for tenant in tenants:
        if tenant.get("tenant_id") == "master":
            tenant["license_key"] = "LIC-NOT-REQUIRED-FOR-MASTER"
            break
    storage.save_tenants(tenants)

    authenticated = storage.authenticate_admin(
        "master@example.com",
        "secret123",
        "desktop-master",
    )
    validated = storage.validate_admin_api_token(
        authenticated["api_token"],
        device_id="desktop-master",
        require_server=False,
    )

    assert authenticated["admin"]["role"] == "master"
    assert validated["role"] == "master"


def test_client_role_is_forbidden_from_platform_clients_dashboard(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)

    master = storage.register_admin(
        name="Master Admin",
        email="master@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-master",
    )
    storage.register_admin_server(
        api_token=master["api_token"],
        device_id="desktop-master",
        server_domain="master-host",
        server_ip="10.0.0.2",
        hardware_hash="hw-master",
    )

    platform_client = storage.register_admin(
        name="Tenant Admin",
        email="tenant@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-tenant",
    )
    bound = storage.register_admin_server(
        api_token=platform_client["api_token"],
        device_id="desktop-tenant",
        server_domain="tenant-host",
        server_ip="10.0.0.3",
        hardware_hash="hw-tenant",
    )

    app = FastAPI()
    app.include_router(admin_router, prefix="/admin")
    app.include_router(analytics_router, prefix="/analytics")
    client = TestClient(app)

    headers = {
        "Authorization": f"Bearer {platform_client['api_token']}",
        "X-Device-Id": "desktop-tenant",
        "X-Server-Id": bound["server_id"],
    }

    analytics_response = client.get("/analytics/live", headers=headers)
    platform_clients_response = client.get("/admin/platform_clients", headers=headers)
    tenant_streams = client.get("/admin/streams", headers=headers)

    assert analytics_response.status_code == 200
    assert platform_clients_response.status_code == 403
    assert tenant_streams.status_code in {200, 503}


def test_platform_clients_dashboard_and_update_check(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    created = storage.register_admin(
        name="Dashboard Admin",
        email="dashboard@example.com",
        password="secret123",
        plan_id="1_year",
        device_id="desktop-main",
    )

    storage.register_install_event(
        admin_id=created["admin"]["admin_id"],
        device_id="desktop-main",
        app_version="0.1.0",
        timestamp="2026-03-20T12:00:00+00:00",
    )
    storage.register_subscription_event(
        admin_id=created["admin"]["admin_id"],
        subscription_plan="1_year",
        start_date=created["admin"]["subscription_start_date"],
        end_date=created["admin"]["subscription_end_date"],
    )
    storage.log_audit_event(
        path="/admin/platform_clients/dashboard",
        method="GET",
        status_code=200,
        admin_id=created["admin"]["admin_id"],
        tenant_id=created["admin"]["tenant_id"],
        device_id="desktop-main",
        server_id="server-1",
        scope="admin",
        duration_ms=18,
    )
    storage.save_release_info(
        {
            "latest_version": "0.2.0",
            "minimum_supported_version": "0.1.0",
            "download_url": "https://example.com/download",
            "release_notes": "New installer available.",
        }
    )

    dashboard = storage.get_platform_client_dashboard(admin_id=created["admin"]["admin_id"])
    update = storage.check_for_desktop_update("0.1.0", platform="win32")

    assert dashboard["summary"]["install_count"] == 1
    assert dashboard["subscriptions"][0]["estimated_revenue"] > 0
    assert dashboard["audit_logs"][0]["path"] == "/admin/platform_clients/dashboard"
    assert update["has_update"] is True
    assert update["latest_version"] == "0.2.0"


def test_subscription_notification_logging(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    created = storage.register_admin(
        name="Notify Admin",
        email="notify@example.com",
        password="secret123",
        plan_id="trial",
        device_id="desktop-a",
    )
    admin = storage.get_admin_by_id(created["admin"]["admin_id"])
    admin["subscription_end"] = "2026-03-25T00:00:00+00:00"
    admin["subscription_end_date"] = admin["subscription_end"]
    storage.save_admins([admin])

    from app.notifications import run_subscription_notification_check
    from app.settings import EmailSettings

    result = run_subscription_notification_check(
        EmailSettings(
            platform_base_url="https://portal.example.com",
            desktop_download_url="https://portal.example.com/download",
        )
    )

    email_logs = storage.load_email_logs()
    assert result["count"] == 1
    assert email_logs[0]["email"] == "notify@example.com"
    assert email_logs[0]["status"] in {"logged", "logged-only"}


def test_license_generate_activate_and_validate(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    created = storage.register_admin(
        name="Licensed Admin",
        email="licensed@example.com",
        password="secret123",
        plan_id="1_year",
        device_id="desktop-a",
    )

    license_item = storage.generate_license_for_admin(admin_id=created["admin"]["admin_id"])
    activated = storage.activate_license_key(
        license_key=license_item["license_key"],
        device_id="desktop-a",
        app_version="0.1.0",
    )
    validated = storage.validate_license_token_payload(
        license_token=activated["license_token"],
        device_id="desktop-a",
    )

    assert license_item["status"] == "inactive"
    assert activated["license"]["status"] == "active"
    assert validated["valid"] is True
    assert validated["license"]["device_id"] == "desktop-a"
