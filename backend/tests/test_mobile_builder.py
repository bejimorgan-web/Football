import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import mobile_builder


def _configure_builder(monkeypatch, tmp_path):
    backend_root = tmp_path / "backend"
    project_root = tmp_path / "project"
    mobile_dir = project_root / "mobile"
    generated_dir = backend_root / "generated_apps"
    queue_dir = backend_root / "build_queue"
    logs_dir = backend_root / "logs"
    tenant_root = backend_root / "data" / "tenants" / "admin-1"
    assets_root = backend_root / "data" / "assets" / "branding" / "admin-1"
    flutter_root = project_root / "flutter-sdk"
    android_main = mobile_dir / "android" / "app" / "src" / "main"

    (android_main / "kotlin" / "com" / "example" / "mobile_new").mkdir(parents=True, exist_ok=True)
    for density in ["mipmap-hdpi", "mipmap-mdpi", "mipmap-xhdpi", "mipmap-xxhdpi", "mipmap-xxxhdpi"]:
        icon_dir = android_main / "res" / density
        icon_dir.mkdir(parents=True, exist_ok=True)
        (icon_dir / "ic_launcher.png").write_bytes(b"default-icon")
    (android_main / "AndroidManifest.xml").write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:label="mobile_new" android:icon="@mipmap/ic_launcher"></application></manifest>',
        encoding="utf-8",
    )
    (android_main / "kotlin" / "com" / "example" / "mobile_new" / "MainActivity.kt").write_text(
        "package com.example.mobile_new\nclass MainActivity\n",
        encoding="utf-8",
    )
    (mobile_dir / "lib" / "config").mkdir(parents=True, exist_ok=True)
    (mobile_dir / "lib" / "config" / "tenant_config.dart").write_text(
        "const String embeddedTenantId = 'default';\nString get embeddedTenantBackendUrl => NetworkConfig.baseUrl;\nconst String embeddedTenantApiToken = '';\n",
        encoding="utf-8",
    )
    (mobile_dir / "pubspec.yaml").write_text(
        "name: football_streaming_mobile\nflutter:\n  uses-material-design: true\n",
        encoding="utf-8",
    )
    (mobile_dir / "android" / "app" / "build.gradle.kts").write_text(
        'android {\n    namespace = "com.example.mobile_new"\n    defaultConfig {\n        applicationId = "com.example.mobile_new"\n        versionCode = flutter.versionCode\n        versionName = flutter.versionName\n    }\n}\n',
        encoding="utf-8",
    )
    (flutter_root / "bin").mkdir(parents=True, exist_ok=True)
    (flutter_root / "bin" / "flutter.bat").write_text("@echo off\n", encoding="utf-8")
    (mobile_dir / "android" / "local.properties").write_text(
        f"sdk.dir={str(project_root / 'android-sdk').replace(chr(92), '/')}\nflutter.sdk={str(flutter_root).replace(chr(92), '/')}\n",
        encoding="utf-8",
    )

    assets_root.mkdir(parents=True, exist_ok=True)
    (assets_root / "logo.png").write_bytes(b"pngdata")
    branding_storage = backend_root / "storage" / "branding" / "goaltv"
    branding_storage.mkdir(parents=True, exist_ok=True)
    (branding_storage / "logo.png").write_bytes(b"tenant-logo")
    (branding_storage / "mobile_icon.png").write_bytes(b"tenant-icon")
    (branding_storage / "splash.png").write_bytes(b"tenant-splash")
    tenant_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mobile_builder, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(mobile_builder, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(mobile_builder, "PRIMARY_MOBILE_PROJECT_DIR", mobile_dir)
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

    assert first["version"] == "1.0.0"
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

    def fake_run(build_id, command, cwd, log_path):
        mobile_builder._log(log_path, f"fake run: {' '.join(command)}")
        if command[:3] == ["flutter", "build", "apk"]:
            apk = Path(cwd) / "build" / "app" / "outputs" / "flutter-apk"
            apk.mkdir(parents=True, exist_ok=True)
            (apk / "app-release.apk").write_bytes(b"apk")

    monkeypatch.setattr(mobile_builder, "_ensure_flutter_available", lambda log_path=None: "C:/FlutterSDK/bin/flutter.bat")
    monkeypatch.setattr(mobile_builder, "_run_flutter_command", fake_run)
    mobile_builder._process_job(job)

    status = mobile_builder.get_build_status("admin-1", job["build_id"])
    assert status["status"] == "completed"
    assert status["progress"] == 100
    assert "fake run: flutter pub get" in status["logs"]
    assert "fake run: flutter clean" in status["logs"]
    assert "fake run: flutter build apk --release" in status["logs"]
    assert status["mobile_app_generated"] is True
    artifact = backend_root / "generated_apps" / "admin-1" / "Goal-TV-1.0.0.apk"
    assert artifact.exists()
    assert tenant_state["mobile_app_generated"] is True
    assert tenant_state["mobile_app_package_id"] == "com.goaltv.mobile"
    restored_manifest = (Path(mobile_builder.PRIMARY_MOBILE_PROJECT_DIR) / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:label="mobile_new"' in restored_manifest


def test_flutter_preflight_requires_installed_sdk(monkeypatch, tmp_path):
    _configure_builder(monkeypatch, tmp_path)
    monkeypatch.setattr(mobile_builder, "_resolve_flutter_executable", lambda: (_ for _ in ()).throw(RuntimeError("missing flutter")))

    try:
        mobile_builder._ensure_flutter_available()
    except RuntimeError as exc:
        assert "Flutter SDK is required before running APK builds" in str(exc)
    else:
        raise AssertionError("Expected missing Flutter preflight error")


def test_android_sdk_preflight_requires_installed_sdk(monkeypatch, tmp_path):
    _configure_builder(monkeypatch, tmp_path)
    monkeypatch.setattr(mobile_builder, "_resolve_android_sdk_dir", lambda: "")

    try:
        mobile_builder._ensure_android_sdk_available()
    except RuntimeError as exc:
        assert "Android SDK is required before running APK builds" in str(exc)
    else:
        raise AssertionError("Expected missing Android SDK preflight error")
