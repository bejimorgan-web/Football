import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import mobile_builder


def _configure_builder(monkeypatch, tmp_path):
    backend_root = tmp_path / "backend"
    project_root = tmp_path / "project"
    template_dir = project_root / "mobile-template"
    generated_dir = backend_root / "generated_apps"
    queue_dir = backend_root / "build_queue"
    logs_dir = backend_root / "logs"
    tenant_root = backend_root / "data" / "tenants" / "admin-1"
    assets_root = backend_root / "data" / "assets" / "branding" / "admin-1"

    template_activity = template_dir / "android" / "app" / "src" / "main" / "kotlin" / "com" / "example" / "mobile_new"
    template_activity.mkdir(parents=True, exist_ok=True)
    (template_dir / "lib" / "config").mkdir(parents=True, exist_ok=True)
    (template_dir / "android" / "app" / "src" / "main" / "res" / "drawable").mkdir(parents=True, exist_ok=True)
    for density in ["mipmap-hdpi", "mipmap-mdpi", "mipmap-xhdpi", "mipmap-xxhdpi", "mipmap-xxxhdpi"]:
        icon_dir = template_dir / "android" / "app" / "src" / "main" / "res" / density
        icon_dir.mkdir(parents=True, exist_ok=True)
        (icon_dir / "ic_launcher.png").write_bytes(b"icon")
    (template_dir / "lib" / "config" / "app_config.dart").write_text(
        "const embeddedAppName='APP_NAME'; const embeddedPackageName='PACKAGE_NAME'; const embeddedServerUrl='SERVER_URL'; const embeddedTenantId='TENANT_ID'; const embeddedPrimaryColor='PRIMARY_COLOR'; const embeddedSecondaryColor='SECONDARY_COLOR'; const embeddedLogoPath='LOGO_PATH'; const embeddedAppVersion='APP_VERSION';",
        encoding="utf-8",
    )
    (template_dir / "lib" / "config" / "backend.dart").write_text("SERVER_URL TENANT_ID", encoding="utf-8")
    (template_dir / "lib" / "config" / "backend_web_stub.dart").write_text("SERVER_URL", encoding="utf-8")
    (template_dir / "lib" / "main.dart").write_text("APP_NAME PACKAGE_NAME SERVER_URL TENANT_ID PRIMARY_COLOR SECONDARY_COLOR LOGO_PATH APP_VERSION", encoding="utf-8")
    (template_dir / "pubspec.yaml").write_text("name: PUBSPEC_NAME\nversion: APP_VERSION+1\n", encoding="utf-8")
    (template_dir / "android" / "app" / "build.gradle.kts").write_text('namespace = "PACKAGE_NAME"\napplicationId = "PACKAGE_NAME"\n', encoding="utf-8")
    (template_dir / "android" / "app" / "src" / "main" / "AndroidManifest.xml").write_text('android:label="APP_NAME"', encoding="utf-8")
    (template_activity / "MainActivity.kt").write_text("package PACKAGE_NAME", encoding="utf-8")
    (template_dir / "android" / "app" / "src" / "main" / "res" / "drawable" / "launch_background.xml").write_text("PRIMARY_COLOR", encoding="utf-8")

    assets_root.mkdir(parents=True, exist_ok=True)
    (assets_root / "logo.png").write_bytes(b"pngdata")
    tenant_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mobile_builder, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(mobile_builder, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(mobile_builder, "MOBILE_TEMPLATE_DIR", template_dir)
    monkeypatch.setattr(mobile_builder, "GENERATED_APPS_DIR", generated_dir)
    monkeypatch.setattr(mobile_builder, "BUILD_QUEUE_DIR", queue_dir)
    monkeypatch.setattr(mobile_builder, "BUILD_QUEUE_JOBS_PATH", queue_dir / "jobs.json")
    monkeypatch.setattr(mobile_builder, "BUILD_WORKSPACES_DIR", queue_dir / "workspaces")
    monkeypatch.setattr(mobile_builder, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(mobile_builder, "BUILD_LOGS_DIR", logs_dir / "mobile-builder")
    tenant_state = {
        "tenant_id": "goaltv",
        "name": "Goal TV",
        "mobile_app_generated": False,
        "mobile_app_package_id": None,
        "mobile_app_created_at": None,
    }
    monkeypatch.setattr(mobile_builder, "get_admin_by_id", lambda admin_id: {"admin_id": admin_id, "tenant_id": "goaltv"})
    monkeypatch.setattr(
        mobile_builder,
        "get_branding_config",
        lambda tenant_id: {
            "tenant_id": tenant_id,
            "backend_url": "https://api.platform.test",
            "branding": {
                "app_name": "Goal TV",
                "package_name": "com.goaltv.mobile",
                "primary_color": "#11B37C",
                "secondary_color": "#7EE3AF",
                "server_url": "https://api.platform.test",
                "logo_file": "/assets/branding/admin-1/logo.png",
                "splash_screen": "",
            },
        },
    )
    monkeypatch.setattr(mobile_builder, "get_admin_storage_path", lambda admin_id: tenant_root)
    monkeypatch.setattr(mobile_builder, "get_tenant", lambda tenant_id: dict(tenant_state))
    monkeypatch.setattr(
        mobile_builder,
        "update_tenant_mobile_app_status",
        lambda tenant_id, **patch: tenant_state.update({**patch, "tenant_id": tenant_id}) or dict(tenant_state),
    )
    mobile_builder.ensure_mobile_builder_storage()
    return backend_root, tenant_state


def test_queue_mobile_build_blocks_duplicate_generation(monkeypatch, tmp_path):
    _configure_builder(monkeypatch, tmp_path)

    first = mobile_builder.queue_mobile_build("admin-1")

    assert first["version"] == "1.0"
    try:
        mobile_builder.queue_mobile_build("admin-1")
    except ValueError as exc:
        assert "already in progress" in str(exc)
    else:
        raise AssertionError("Expected duplicate-generation error")


def test_mobile_build_limit(monkeypatch, tmp_path):
    _configure_builder(monkeypatch, tmp_path)
    for _ in range(5):
        mobile_builder._save_jobs(
            mobile_builder._load_jobs()
            + [{
                "build_id": f"job-{_}",
                "admin_id": "admin-1",
                "status": "failed",
                "created_at": f"{mobile_builder.utc_now_iso()}",
            }]
        )

    try:
        mobile_builder.queue_mobile_build("admin-1")
    except ValueError as exc:
        assert "Maximum 5 builds per day" in str(exc)
    else:
        raise AssertionError("Expected daily build limit error")


def test_process_job_completes_and_generates_apk(monkeypatch, tmp_path):
    backend_root, tenant_state = _configure_builder(monkeypatch, tmp_path)
    job = mobile_builder.queue_mobile_build("admin-1")

    def fake_run(command, cwd, log_path):
        if command[:3] == ["flutter", "build", "apk"]:
            apk = Path(cwd) / "build" / "app" / "outputs" / "flutter-apk"
            apk.mkdir(parents=True, exist_ok=True)
            (apk / "app-release.apk").write_bytes(b"apk")

    monkeypatch.setattr(mobile_builder, "_run_flutter_command", fake_run)
    mobile_builder._process_job(job)

    status = mobile_builder.get_build_status("admin-1", job["build_id"])
    assert status["status"] == "completed"
    assert status["progress"] == 100
    assert status["mobile_app_generated"] is True
    artifact = backend_root / "generated_apps" / "admin-1" / "Goal-TV-1.0.apk"
    assert artifact.exists()
    assert tenant_state["mobile_app_generated"] is True
    assert tenant_state["mobile_app_package_id"] == "com.goaltv.mobile"
