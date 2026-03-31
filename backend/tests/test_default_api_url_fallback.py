import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import api_config, storage
from app.config import DEFAULT_API_URL
from app.routes.mobile_builder import mobile_runtime_config


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
    monkeypatch.setattr(storage, "MASTER_DATA_DIR", data_dir / "master")
    monkeypatch.setattr(api_config, "DATA_DIR", data_dir)
    monkeypatch.setattr(api_config, "API_CONFIG_PATH", data_dir / "api_config.json")
    storage._ACTIVE_VIEWERS.clear()
    storage.ensure_storage_files()
    api_config.ensure_api_config_storage()


def test_empty_server_url_falls_back_to_default(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    storage.upsert_tenant(tenant_id="fallback-tv", name="Fallback TV", backend_url="")
    storage.update_tenant_branding("fallback-tv", {"server_url": "", "api_base_url": ""})

    branding = storage.get_branding_config("fallback-tv")

    assert branding["backend_url"] == DEFAULT_API_URL
    assert branding["backend_url_source"] == "default_api_base"
    assert "configured API base URL" in branding["backend_url_notice"]


def test_manual_server_url_override_still_works(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    storage.upsert_tenant(tenant_id="override-tv", name="Override TV", backend_url="https://tenant.example.com")
    storage.update_tenant_branding("override-tv", {"server_url": "https://tenant.example.com"})

    branding = storage.get_branding_config("override-tv")

    assert branding["backend_url"] == "https://tenant.example.com"
    assert branding["backend_url_source"] == "configured"
    assert branding["backend_url_notice"] == ""


def test_mobile_config_always_returns_resolved_url(monkeypatch, tmp_path):
    _configure_temp_storage(monkeypatch, tmp_path)
    storage.upsert_tenant(tenant_id="mobile-fallback", name="Mobile Fallback", backend_url="")
    storage.update_tenant_branding("mobile-fallback", {"server_url": "", "api_base_url": ""})

    tenant_payload = storage.get_branding_config("mobile-fallback")
    runtime_payload = mobile_runtime_config("mobile-fallback")

    assert tenant_payload["backend_url"] == DEFAULT_API_URL
    assert tenant_payload["backend_url_source"] == "default_api_base"
    assert runtime_payload["server_url"] == DEFAULT_API_URL
    assert runtime_payload["api_url"] == DEFAULT_API_URL
