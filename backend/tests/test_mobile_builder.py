import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import mobile_build_artifacts, mobile_build_store
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
    monkeypatch.setattr(mobile_builder, "BUILD_WORKSPACES_DIR", queue_dir / "workspaces")
    monkeypatch.setattr(mobile_builder, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(mobile_builder, "BUILD_LOGS_DIR", logs_dir / "mobile-builder")
    monkeypatch.setattr(mobile_builder, "DOCKERFILE_PATH", backend_root / "docker" / "flutter-android-builder.Dockerfile")
    monkeypatch.setattr(mobile_builder, "MOBILE_BUILDER_BACKEND", "docker")
    monkeypatch.setattr(mobile_builder, "DOCKER_IMAGE_NAME", "football-streaming-mobile-builder:latest")
    monkeypatch.setattr(mobile_build_store, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(mobile_build_store, "DATA_DIR", backend_root / "data")
    monkeypatch.setattr(mobile_build_store, "MOBILE_BUILD_DB_PATH", backend_root / "data" / "mobile_builds.db")
    monkeypatch.setattr(mobile_build_artifacts, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(mobile_build_artifacts, "LOCAL_ARTIFACTS_ROOT", generated_dir)
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


def test_mobile_build_worker_disabled_by_default_on_render(monkeypatch):
    monkeypatch.delenv("MOBILE_BUILD_WORKER_ENABLED", raising=False)
    monkeypatch.setenv("RENDER", "true")
    assert mobile_builder.mobile_build_worker_enabled() is False


def test_mobile_build_worker_env_override(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("MOBILE_BUILD_WORKER_ENABLED", "true")
    assert mobile_builder.mobile_build_worker_enabled() is True


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
        mobile_build_store.create_mobile_build_job(
            {
                "build_id": f"job-{_}",
                "admin_id": "admin-1",
                "tenant_id": "goaltv",
                "status": "failed",
                "progress": 0,
                "created_at": f"{mobile_builder.utc_now_iso()}",
                "updated_at": f"{mobile_builder.utc_now_iso()}",
                "completed_at": f"{mobile_builder.utc_now_iso()}",
                "version": "1.0.0",
                "app_name": "Goal TV",
                "package_name": "com.goaltv.mobile",
                "server_url": "https://api.platform.test",
                "primary_color": "#11B37C",
                "secondary_color": "#7EE3AF",
                "logo_file": "",
                "splash_screen": "",
                "artifact_name": "",
                "artifact_path": "",
                "artifact_storage": "local",
                "artifact_key": "",
                "artifact_url": "",
                "error": "",
                "logs": "",
                "worker_id": "",
            }
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

    def fake_run(build_id, command, cwd, log_path, env=None):
        mobile_builder._log(log_path, f"fake run: {' '.join(command)}")
        if command[-3:] == ["build", "apk", "--release"]:
            apk = Path(cwd) / "build" / "app" / "outputs" / "flutter-apk"
            apk.mkdir(parents=True, exist_ok=True)
            (apk / "app-release.apk").write_bytes(b"apk")

    monkeypatch.setattr(mobile_builder, "_ensure_docker_build_image", lambda build_id, log_path: "docker")
    monkeypatch.setattr(mobile_builder, "_run_logged_command", fake_run)
    mobile_builder._process_job(job)

    status = mobile_builder.get_build_status("admin-1", job["build_id"])
    assert status["status"] == "completed"
    assert status["progress"] == 100
    assert "fake run: docker run" in status["logs"]
    assert "[Docker] Build started" in status["logs"]
    assert "[Docker] Build finished" in status["logs"]
    assert " /opt/flutter/bin/flutter pub get" in status["logs"]
    assert " /opt/flutter/bin/flutter clean" in status["logs"]
    assert " /opt/flutter/bin/flutter build apk --release" in status["logs"]
    assert status["mobile_app_generated"] is True
    artifact = backend_root / "generated_apps" / "goaltv" / "Goal-TV-1.0.0.apk"
    assert artifact.exists()
    assert tenant_state["mobile_app_generated"] is True
    assert tenant_state["mobile_app_package_id"] == "com.goaltv.mobile"
    restored_manifest = (Path(mobile_builder.PRIMARY_MOBILE_PROJECT_DIR) / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:label="mobile_new"' in restored_manifest


def test_build_tenant_apk_in_docker_stages_workspace_and_stores_per_tenant(monkeypatch, tmp_path):
    backend_root, _tenant_state = _configure_builder(monkeypatch, tmp_path)
    log_path = backend_root / "logs" / "mobile-builder" / "docker-build.log"
    tenant_data = mobile_builder._resolve_branding("admin-1")

    def fake_run(build_id, command, cwd, log_path, env=None):
        mobile_builder._log(log_path, f"fake run: {' '.join(command)}")
        if command[-3:] == ["build", "apk", "--release"]:
            apk = Path(cwd) / "build" / "app" / "outputs" / "flutter-apk"
            apk.mkdir(parents=True, exist_ok=True)
            (apk / "app-release.apk").write_bytes(b"docker-apk")

    monkeypatch.setattr(mobile_builder, "_ensure_docker_build_image", lambda build_id, log_path: "docker")
    monkeypatch.setattr(mobile_builder, "_run_logged_command", fake_run)

    result = mobile_builder.build_tenant_apk_in_docker(
        build_id="build-1",
        tenant_data=tenant_data,
        version="1.0.0",
        admin_id="admin-1",
        log_path=log_path,
    )

    artifact = Path(result["artifact_path"])
    assert artifact.exists()
    assert artifact == backend_root / "generated_apps" / "goaltv" / "Goal-TV-1.0.0.apk"
    log_contents = log_path.read_text(encoding="utf-8")
    assert "[Docker] Build started" in log_contents
    assert "[Docker] Build finished" in log_contents
    assert "football-streaming-mobile-builder:latest" in log_contents
    workspace_local_properties = backend_root / "build_queue" / "workspaces" / "build-1" / "mobile" / "android" / "local.properties"
    workspace_manifest = backend_root / "build_queue" / "workspaces" / "build-1" / "mobile" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    assert "/opt/flutter" in workspace_local_properties.read_text(encoding="utf-8")
    assert "/opt/android-sdk" in workspace_local_properties.read_text(encoding="utf-8")
    assert '@string/app_name' in workspace_manifest.read_text(encoding="utf-8")


def test_flutter_preflight_skips_host_validation_when_docker_enabled(monkeypatch, tmp_path):
    _configure_builder(monkeypatch, tmp_path)
    monkeypatch.setattr(mobile_builder, "_resolve_flutter_executable", lambda: "/opt/flutter/bin/flutter")
    assert mobile_builder._ensure_flutter_available() == "/opt/flutter/bin/flutter"


def test_android_sdk_preflight_skips_host_validation_when_docker_enabled(monkeypatch, tmp_path):
    _configure_builder(monkeypatch, tmp_path)
    monkeypatch.setattr(mobile_builder, "_resolve_android_sdk_dir", lambda: (_ for _ in ()).throw(AssertionError("host SDK lookup should be skipped")))
    assert mobile_builder._ensure_android_sdk_available() == "/opt/android-sdk"


def test_local_flutter_execution_is_disabled(monkeypatch, tmp_path):
    _configure_builder(monkeypatch, tmp_path)

    try:
        mobile_builder._run_flutter_command(
            "build-1",
            ["flutter", "build", "apk", "--release"],
            mobile_builder.PRIMARY_MOBILE_PROJECT_DIR,
            mobile_builder.BUILD_LOGS_DIR / "local-disabled.log",
        )
    except RuntimeError as exc:
        assert "Local Flutter execution is disabled" in str(exc)
    else:
        raise AssertionError("Expected local Flutter execution to be disabled")
