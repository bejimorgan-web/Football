from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from app.storage import (
    get_admin_by_id,
    get_admin_storage_path,
    get_branding_config,
    save_mobile_app_record,
    get_tenant,
    update_tenant_mobile_app_status,
)

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
PRIMARY_MOBILE_PROJECT_DIR = PROJECT_ROOT / "mobile"
GENERATED_APPS_DIR = BACKEND_ROOT / "generated_apps"
BUILD_QUEUE_DIR = BACKEND_ROOT / "build_queue"
BUILD_QUEUE_JOBS_PATH = BUILD_QUEUE_DIR / "jobs.json"
BUILD_WORKSPACES_DIR = BUILD_QUEUE_DIR / "workspaces"
LOGS_DIR = BACKEND_ROOT / "logs"
BUILD_LOGS_DIR = LOGS_DIR / "mobile-builder"

MAX_BUILDS_PER_DAY = 5
JOB_LOCK = threading.Lock()
JOB_EVENT = threading.Event()
WORKER_STOP_EVENT = threading.Event()
WORKER_THREAD: Optional[threading.Thread] = None
ACTIVE_PROCESSES: Dict[str, subprocess.Popen] = {}
ACTIVE_PROCESSES_LOCK = threading.Lock()

PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
JAVA_RESERVED_WORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class",
    "const", "continue", "default", "do", "double", "else", "enum", "extends", "final",
    "finally", "float", "for", "goto", "if", "implements", "import", "instanceof", "int",
    "interface", "long", "native", "new", "package", "private", "protected", "public",
    "return", "short", "static", "strictfp", "super", "switch", "synchronized", "this",
    "throw", "throws", "transient", "try", "void", "volatile", "while",
}


class BuildCancelledError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_mobile_builder_storage() -> None:
    GENERATED_APPS_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not BUILD_QUEUE_JOBS_PATH.exists():
        _write_json(BUILD_QUEUE_JOBS_PATH, [])


def _read_build_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def start_mobile_build_worker() -> None:
    global WORKER_THREAD
    ensure_mobile_builder_storage()
    _recover_interrupted_jobs()
    if WORKER_THREAD and WORKER_THREAD.is_alive():
        return
    WORKER_STOP_EVENT.clear()
    WORKER_THREAD = threading.Thread(target=_worker_loop, name="mobile-build-worker", daemon=True)
    WORKER_THREAD.start()


def stop_mobile_build_worker() -> None:
    WORKER_STOP_EVENT.set()
    JOB_EVENT.set()
    global WORKER_THREAD
    if WORKER_THREAD and WORKER_THREAD.is_alive():
        WORKER_THREAD.join(timeout=2)
    WORKER_THREAD = None


def _worker_loop() -> None:
    while not WORKER_STOP_EVENT.is_set():
        job = _next_queued_job()
        if job is None:
            JOB_EVENT.wait(timeout=1)
            JOB_EVENT.clear()
            continue
        _process_job(job)


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_jobs() -> List[Dict[str, object]]:
    ensure_mobile_builder_storage()
    payload = _read_json(BUILD_QUEUE_JOBS_PATH, [])
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _save_jobs(jobs: List[Dict[str, object]]) -> None:
    _write_json(BUILD_QUEUE_JOBS_PATH, jobs)


def _recover_interrupted_jobs() -> None:
    recovered: List[Dict[str, object]] = []
    with JOB_LOCK:
        jobs = _load_jobs()
        changed = False
        now = utc_now_iso()
        for item in jobs:
            status = str(item.get("status") or "").strip().lower()
            if status == "building":
                item.update(
                    {
                        "status": "failed",
                        "progress": 0,
                        "error": str(item.get("error") or "Build interrupted before completion."),
                        "updated_at": now,
                        "completed_at": now,
                    }
                )
                recovered.append(dict(item))
                changed = True
            elif status == "cancelling":
                item.update(
                    {
                        "status": "cancelled",
                        "progress": 0,
                        "error": str(item.get("error") or "Build cancelled while the worker was offline."),
                        "updated_at": now,
                        "completed_at": now,
                    }
                )
                recovered.append(dict(item))
                changed = True
        if changed:
            _save_jobs(jobs)
    for item in recovered:
        _sync_version_history_entry(item)


def _update_job(build_id: str, patch: Dict[str, object]) -> Dict[str, object]:
    with JOB_LOCK:
        jobs = _load_jobs()
        updated = None
        for item in jobs:
            if str(item.get("build_id") or "") == build_id:
                item.update(patch)
                updated = dict(item)
                break
        if updated is None:
            raise ValueError("Build job not found.")
        _save_jobs(jobs)
    _sync_version_history_entry(updated)
    return updated


def _clear_build_state(build_id: str, *, status: str, error: str) -> Dict[str, object]:
    return _update_job(
        build_id,
        {
            "status": status,
            "progress": 0,
            "error": error,
            "artifact_name": "",
            "artifact_path": "",
            "updated_at": utc_now_iso(),
            "completed_at": utc_now_iso(),
        },
    )


def _next_queued_job() -> Optional[Dict[str, object]]:
    with JOB_LOCK:
        jobs = _load_jobs()
        queued = [
            item for item in jobs
            if str(item.get("status") or "") == "queued"
        ]
        queued.sort(key=lambda item: str(item.get("created_at") or ""))
        return dict(queued[0]) if queued else None


def _admin_versions_path(admin_id: str) -> Path:
    return get_admin_storage_path(admin_id) / "app_versions.json"


def _load_version_history(admin_id: str) -> List[Dict[str, object]]:
    path = _admin_versions_path(admin_id)
    payload = _read_json(path, [])
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _save_version_history(admin_id: str, items: List[Dict[str, object]]) -> None:
    _write_json(_admin_versions_path(admin_id), items)


def _increment_version(previous: Optional[str]) -> str:
    major, minor, patch = _normalize_semver(previous)
    return f"{major}.{minor}.{patch + 1}"


def _version_code(version: str) -> int:
    major, minor, patch = _normalize_semver(version)
    return (major * 10000) + (minor * 100) + patch


def _normalize_semver(version: Optional[str]) -> tuple[int, int, int]:
    raw_parts = [part for part in str(version or "").split(".") if part != ""]
    numeric_parts = []
    for part in raw_parts[:3]:
        try:
            numeric_parts.append(int(part))
        except ValueError:
            numeric_parts.append(0)
    while len(numeric_parts) < 3:
        numeric_parts.append(0)
    major, minor, patch = numeric_parts[:3]
    if major <= 0:
        major = 1
    return major, minor, patch


def _next_version_for_admin(admin_id: str) -> str:
    history = _load_version_history(admin_id)
    if not history:
        return "1.0.0"
    history.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return _increment_version(str(history[0].get("version") or "1.0.0"))


def _sync_version_history_entry(job: Dict[str, object]) -> None:
    admin_id = str(job.get("admin_id") or "").strip()
    if not admin_id:
        return
    history = _load_version_history(admin_id)
    build_id = str(job.get("build_id") or "")
    entry = next((item for item in history if str(item.get("build_id") or "") == build_id), None)
    if entry is None:
        entry = {}
        history.append(entry)
    entry.update(
        {
            "version": str(job.get("version") or ""),
            "build_id": build_id,
            "created_at": str(job.get("created_at") or ""),
            "status": str(job.get("status") or ""),
            "apk_name": str(job.get("artifact_name") or ""),
        }
    )
    history.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    _save_version_history(admin_id, history)


def _slugify_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip()).strip("-")
    return cleaned or "app"


def _read_java_properties(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    result: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _resolve_flutter_root() -> str:
    candidates = []

    flutter_root = os.environ.get("FLUTTER_ROOT", "").strip()
    if flutter_root:
        candidates.append(Path(flutter_root))

    project_local_properties = PRIMARY_MOBILE_PROJECT_DIR / "android" / "local.properties"
    configured_flutter_root = _read_java_properties(project_local_properties).get("flutter.sdk", "").strip()
    if configured_flutter_root:
        candidates.append(Path(configured_flutter_root))

    flutter_binary = shutil.which("flutter.bat") or shutil.which("flutter")
    if flutter_binary:
        candidates.append(Path(flutter_binary).resolve().parent.parent)

    for candidate in candidates:
        flutter_bat = candidate / "bin" / "flutter.bat"
        flutter_cmd = candidate / "bin" / "flutter"
        if flutter_bat.exists() or flutter_cmd.exists():
            return str(candidate.resolve())

    raise RuntimeError(
        "Flutter SDK could not be resolved. Configure FLUTTER_ROOT or "
        "mobile/android/local.properties with flutter.sdk."
    )


def _resolve_flutter_executable() -> str:
    flutter_root = Path(_resolve_flutter_root())
    flutter_bat = flutter_root / "bin" / "flutter.bat"
    if flutter_bat.exists():
        return str(flutter_bat)
    flutter_cmd = flutter_root / "bin" / "flutter"
    if flutter_cmd.exists():
        return str(flutter_cmd)
    raise RuntimeError(f"Flutter executable not found under {flutter_root}.")


def _resolve_android_sdk_dir() -> str:
    candidates = [
        os.environ.get("ANDROID_SDK_ROOT", "").strip(),
        os.environ.get("ANDROID_HOME", "").strip(),
        _read_java_properties(PRIMARY_MOBILE_PROJECT_DIR / "android" / "local.properties").get("sdk.dir", "").strip(),
    ]
    for value in candidates:
        if value and Path(value).exists():
            return str(Path(value).resolve())
    return ""


def _pubspec_name(package_name: str) -> str:
    return str(package_name or "").replace(".", "_").replace("-", "_").lower()


def _sanitize_package_name(package_name: str) -> str:
    parts = [part.strip().lower() for part in str(package_name or "").split(".") if part.strip()]
    sanitized = []
    for index, part in enumerate(parts):
        candidate = re.sub(r"[^a-z0-9_]", "_", part)
        if not candidate:
            candidate = f"app{index + 1}"
        if candidate[0].isdigit():
            candidate = f"app_{candidate}"
        if candidate in JAVA_RESERVED_WORDS:
            candidate = f"{candidate}app"
        sanitized.append(candidate)
    return ".".join(sanitized)


def _resolve_branding(admin_id: str) -> Dict[str, object]:
    admin = get_admin_by_id(admin_id)
    if admin is None:
        raise ValueError("Admin not found.")
    tenant_id = str(admin.get("tenant_id") or "").strip()
    branding_payload = get_branding_config(tenant_id)
    branding = dict(branding_payload.get("branding") or {})
    effective_tenant_id = str(branding_payload.get("tenant_id") or tenant_id).strip()
    server_url = str(branding.get("server_url") or branding_payload.get("backend_url") or branding.get("api_base_url") or "").strip()
    package_name = _sanitize_package_name(str(branding.get("package_name") or "").strip().lower())
    app_name = str(branding.get("app_name") or admin.get("name") or "Football Streaming").strip()
    primary = str(branding.get("primary_color") or "#11B37C").strip()
    secondary = str(branding.get("secondary_color") or branding.get("accent_color") or "#7EE3AF").strip()
    logo_file = str(branding.get("logo_file") or branding.get("logo_url") or "").strip()
    splash_screen = str(branding.get("splash_screen") or "").strip()
    if not package_name or not PACKAGE_RE.match(package_name):
        raise ValueError("A valid Android package name is required in tenant branding.")
    if not server_url:
        raise ValueError("A tenant server URL is required before generating an APK.")
    if not HEX_COLOR_RE.match(primary):
        raise ValueError("Primary color must use #RRGGBB format.")
    if not HEX_COLOR_RE.match(secondary):
        raise ValueError("Secondary color must use #RRGGBB format.")
    return {
        "admin_id": admin_id,
        "tenant_id": effective_tenant_id,
        "app_name": app_name,
        "package_name": package_name,
        "pubspec_name": _pubspec_name(package_name),
        "server_url": server_url.rstrip("/"),
        "primary_color": primary.upper(),
        "secondary_color": secondary.upper(),
        "logo_file": logo_file,
        "splash_screen": splash_screen,
    }


def _tenant_mobile_app_state(admin_id: str) -> Dict[str, object]:
    admin = get_admin_by_id(admin_id)
    if admin is None:
        raise ValueError("Admin not found.")
    tenant_id = str(admin.get("tenant_id") or "").strip()
    if not tenant_id:
        raise ValueError("Tenant not found for admin.")
    tenant = get_tenant(tenant_id)
    return {
        "tenant_id": tenant_id,
        "mobile_app_generated": bool(tenant.get("mobile_app_generated") is True),
        "mobile_app_package_id": str(tenant.get("mobile_app_package_id") or "").strip(),
        "mobile_app_created_at": str(tenant.get("mobile_app_created_at") or "").strip(),
    }


def _builds_today(admin_id: str) -> int:
    today = datetime.now(UTC).date().isoformat()
    return sum(1 for item in _load_jobs() if str(item.get("admin_id") or "") == admin_id and str(item.get("created_at") or "").startswith(today))


def queue_mobile_build(admin_id: str) -> Dict[str, object]:
    ensure_mobile_builder_storage()
    if _builds_today(admin_id) >= MAX_BUILDS_PER_DAY:
        raise ValueError("Daily build limit reached. Maximum 5 builds per day.")
    if not PRIMARY_MOBILE_PROJECT_DIR.exists():
        raise ValueError("mobile directory is missing.")
    tenant_state = _tenant_mobile_app_state(admin_id)
    if tenant_state["mobile_app_generated"]:
        raise ValueError("Mobile application already generated for this tenant.")
    existing_job = next(
        (
            item for item in _load_jobs()
            if str(item.get("admin_id") or "") == admin_id
            and str(item.get("status") or "") in {"queued", "building", "completed"}
        ),
        None,
    )
    if existing_job is not None:
        if str(existing_job.get("status") or "") == "completed":
            raise ValueError("Mobile application already generated for this tenant.")
        raise ValueError("Mobile application generation is already in progress for this tenant.")
    branding = _resolve_branding(admin_id)
    build_id = uuid4().hex
    created_at = utc_now_iso()
    job = {
        "build_id": build_id,
        "admin_id": admin_id,
        "tenant_id": branding["tenant_id"],
        "status": "queued",
        "progress": 5,
        "created_at": created_at,
        "updated_at": created_at,
        "version": _next_version_for_admin(admin_id),
        "app_name": branding["app_name"],
        "package_name": branding["package_name"],
        "server_url": branding["server_url"],
        "primary_color": branding["primary_color"],
        "secondary_color": branding["secondary_color"],
        "logo_file": branding["logo_file"],
        "splash_screen": branding["splash_screen"],
        "artifact_name": "",
        "artifact_path": "",
        "error": "",
        "log_path": str((BUILD_LOGS_DIR / f"{build_id}.log").resolve()),
    }
    with JOB_LOCK:
        jobs = _load_jobs()
        jobs.append(job)
        _save_jobs(jobs)
    _sync_version_history_entry(job)
    JOB_EVENT.set()
    return job


def list_build_history(admin_id: str) -> List[Dict[str, object]]:
    jobs = [item for item in _load_jobs() if str(item.get("admin_id") or "") == admin_id]
    jobs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return jobs


def get_build(admin_id: str, build_id: str) -> Dict[str, object]:
    job = next((item for item in _load_jobs() if str(item.get("build_id") or "") == build_id), None)
    if job is None:
        raise ValueError("Build job not found.")
    if str(job.get("admin_id") or "") != admin_id:
        raise PermissionError("You cannot access another tenant's build.")
    return job


def get_build_download_path(admin_id: str, build_id: str) -> Path:
    job = get_build(admin_id, build_id)
    if str(job.get("status") or "") != "completed":
        raise ValueError("Build is not completed yet.")
    artifact_path = Path(str(job.get("artifact_path") or ""))
    if not artifact_path.exists():
        raise ValueError("Generated APK file is missing.")
    return artifact_path


def get_build_status(admin_id: str, build_id: str) -> Dict[str, object]:
    job = get_build(admin_id, build_id)
    tenant_state = _tenant_mobile_app_state(admin_id)
    log_path = Path(str(job.get("log_path") or BUILD_LOGS_DIR / f"{build_id}.log"))
    return {
        "build_id": build_id,
        "status": str(job.get("status") or "queued"),
        "progress": int(job.get("progress") or 0),
        "version": str(job.get("version") or ""),
        "error": str(job.get("error") or ""),
        "artifact_name": str(job.get("artifact_name") or ""),
        "created_at": str(job.get("created_at") or ""),
        "updated_at": str(job.get("updated_at") or ""),
        "log_path": str(log_path),
        "logs": _read_build_log(log_path),
        "mobile_app_generated": bool(tenant_state.get("mobile_app_generated")),
        "mobile_app_package_id": str(tenant_state.get("mobile_app_package_id") or ""),
        "mobile_app_created_at": str(tenant_state.get("mobile_app_created_at") or ""),
    }


def cancel_mobile_build(admin_id: str, build_id: str) -> Dict[str, object]:
    job = get_build(admin_id, build_id)
    status = str(job.get("status") or "").strip().lower()
    if status in {"completed", "failed", "cancelled"}:
        raise ValueError("Build cannot be cancelled in its current state.")

    patch = {
        "updated_at": utc_now_iso(),
        "completed_at": utc_now_iso(),
        "error": "Build cancelled by user.",
    }

    if status == "queued":
        patch["status"] = "cancelled"
        patch["progress"] = 0
        return _update_job(build_id, patch)

    patch["status"] = "cancelling"
    updated = _update_job(build_id, patch)
    with ACTIVE_PROCESSES_LOCK:
        process = ACTIVE_PROCESSES.get(build_id)
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except Exception:
            pass
    return updated


def _is_cancellation_requested(build_id: str) -> bool:
    try:
        job = next((item for item in _load_jobs() if str(item.get("build_id") or "") == build_id), None)
    except Exception:
        job = None
    if job is None:
        return False
    return str(job.get("status") or "").strip().lower() in {"cancelling", "cancelled"}


def _process_job(job: Dict[str, object]) -> None:
    build_id = str(job.get("build_id") or "")
    admin_id = str(job.get("admin_id") or "")
    log_path = BUILD_LOGS_DIR / f"{build_id}.log"
    project_dir = PRIMARY_MOBILE_PROJECT_DIR
    staged_files: Optional[Dict[Path, Optional[bytes]]] = None
    try:
        _update_job(build_id, {"status": "building", "progress": 15, "updated_at": utc_now_iso(), "error": ""})
        _log(log_path, f"Starting build {build_id} for admin {admin_id}")
        _log(log_path, f"Working directory: {project_dir}")
        _log(log_path, f"Flutter executable: {_resolve_flutter_executable()}")
        if not project_dir.exists():
            raise RuntimeError(f"Mobile project directory not found: {project_dir}")
        branding = _resolve_branding(admin_id)
        staged_files = _stage_mobile_project(project_dir, branding, str(job.get("version") or "1.0.0"), log_path)
        _update_job(build_id, {"progress": 30, "updated_at": utc_now_iso()})
        _run_flutter_command(
            build_id,
            ["flutter", "pub", "get"],
            project_dir,
            log_path,
        )
        _update_job(build_id, {"progress": 45, "updated_at": utc_now_iso()})
        _run_flutter_command(
            build_id,
            ["flutter", "clean"],
            project_dir,
            log_path,
        )
        _update_job(build_id, {"progress": 65, "updated_at": utc_now_iso()})
        _run_flutter_command(
            build_id,
            ["flutter", "build", "apk", "--release"],
            project_dir,
            log_path,
        )
        _update_job(build_id, {"progress": 90, "updated_at": utc_now_iso()})
        source_apk = project_dir / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk"
        if not source_apk.exists():
            raise RuntimeError("Flutter build completed but app-release.apk was not found.")
        tenant_dir = GENERATED_APPS_DIR / admin_id
        tenant_dir.mkdir(parents=True, exist_ok=True)
        artifact_name = f"{_slugify_filename(str(job.get('app_name') or 'App'))}-{job.get('version')}.apk"
        target_path = tenant_dir / artifact_name
        shutil.copy2(source_apk, target_path)
        _update_job(
            build_id,
            {
                "status": "completed",
                "progress": 100,
                "artifact_name": artifact_name,
                "artifact_path": str(target_path.resolve()),
                "updated_at": utc_now_iso(),
                "completed_at": utc_now_iso(),
            },
        )
        update_tenant_mobile_app_status(
            str(job.get("tenant_id") or ""),
            mobile_app_generated=True,
            mobile_app_package_id=str(job.get("package_name") or ""),
            mobile_app_created_at=utc_now_iso(),
        )
        save_mobile_app_record(
            tenant_id=str(job.get("tenant_id") or ""),
            package_id=str(job.get("package_name") or ""),
            app_name=str(job.get("app_name") or ""),
            logo_url=str(branding.get("logo_file") or ""),
            theme_color=str(job.get("primary_color") or ""),
            generated_at=utc_now_iso(),
            artifact_name=artifact_name,
            build_id=build_id,
        )
        _log(log_path, f"Build completed: {target_path}")
    except BuildCancelledError as exc:
        _clear_build_state(build_id, status="cancelled", error=str(exc))
        _log(log_path, f"Build cancelled: {exc}")
    except Exception as exc:
        _clear_build_state(build_id, status="failed", error=str(exc))
        _log(log_path, f"Build failed: {exc}")
    finally:
        if staged_files is not None:
            _restore_staged_files(staged_files, log_path)


def _stage_mobile_project(project_dir: Path, branding: Dict[str, object], version: str, log_path: Path) -> Dict[Path, Optional[bytes]]:
    version_code = str(_version_code(version))
    package_name = str(branding["package_name"])
    app_name = str(branding["app_name"])
    android_root = project_dir / "android" / "app" / "src" / "main"
    manifest_path = android_root / "AndroidManifest.xml"
    strings_path = android_root / "res" / "values" / "strings.xml"
    pubspec_path = project_dir / "pubspec.yaml"
    build_gradle_path = project_dir / "android" / "app" / "build.gradle.kts"
    tenant_config_path = project_dir / "lib" / "config" / "tenant_config.dart"
    local_properties = project_dir / "android" / "local.properties"
    kotlin_root = android_root / "kotlin"
    source_activity = next(kotlin_root.rglob("MainActivity.kt"), None)
    if source_activity is None:
        raise RuntimeError("MainActivity.kt not found in mobile Android sources.")
    target_activity = kotlin_root / Path(*package_name.split(".")) / "MainActivity.kt"

    touched: List[Path] = [
        manifest_path,
        strings_path,
        pubspec_path,
        build_gradle_path,
        tenant_config_path,
        local_properties,
        source_activity,
        target_activity,
    ]
    touched.extend(project_dir.glob("android/app/src/main/res/mipmap-*/ic_launcher.png"))
    touched.extend(
        [
            project_dir / "assets" / "branding" / "logo.png",
            project_dir / "assets" / "branding" / "app_icon.png",
            project_dir / "assets" / "branding" / "splash.png",
        ]
    )
    snapshots = _snapshot_files(touched)

    _write_android_manifest(manifest_path, log_path)
    _write_strings_xml(strings_path, app_name, log_path)
    _write_build_gradle(build_gradle_path, package_name, version, version_code, log_path)
    _write_tenant_config(tenant_config_path, branding, log_path)
    _write_pubspec_assets(pubspec_path, log_path)
    _write_main_activity_package(source_activity, target_activity, package_name, log_path)

    flutter_root = _resolve_flutter_root()
    android_sdk_dir = _resolve_android_sdk_dir()
    properties_lines = [f"flutter.sdk={flutter_root.replace(chr(92), chr(47))}"]
    if android_sdk_dir:
        properties_lines.insert(0, f"sdk.dir={android_sdk_dir.replace(chr(92), chr(47))}")
        _log(log_path, f"Configured sdk.dir from {android_sdk_dir}")
    local_properties.write_text("\n".join(properties_lines) + "\n", encoding="utf-8")
    _log(log_path, f"Configured flutter.sdk from {flutter_root}")

    _copy_branding_assets(project_dir, branding, log_path)
    _replace_launcher_icons(project_dir, str(branding.get("tenant_id") or ""), str(branding.get("logo_file") or ""), log_path)
    return snapshots


def _snapshot_files(paths: List[Path]) -> Dict[Path, Optional[bytes]]:
    snapshot: Dict[Path, Optional[bytes]] = {}
    for path in paths:
        if path in snapshot:
            continue
        snapshot[path] = path.read_bytes() if path.exists() else None
    return snapshot


def _restore_staged_files(snapshot: Dict[Path, Optional[bytes]], log_path: Path) -> None:
    for path, original_bytes in snapshot.items():
        if original_bytes is None:
            if path.exists():
                if path.is_file():
                    path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original_bytes)
    _log(log_path, "Restored staged mobile project files after build.")


def _write_android_manifest(path: Path, log_path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    updated = re.sub(r'android:label="[^"]*"', 'android:label="@string/app_name"', content, count=1)
    path.write_text(updated, encoding="utf-8")
    _log(log_path, f"Updated Android manifest label in {path}")


def _write_strings_xml(path: Path, app_name: str, log_path: Path) -> None:
    escaped_app_name = (
        str(app_name)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', '\\"')
        .replace("'", "\\'")
    )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<resources>\n'
        f'    <string name="app_name">{escaped_app_name}</string>\n'
        '</resources>\n'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    _log(log_path, f"Wrote Android app name resources to {path}")


def _write_build_gradle(path: Path, package_name: str, version: str, version_code: str, log_path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    content = re.sub(r'namespace\s*=\s*"[^"]+"', f'namespace = "{package_name}"', content, count=1)
    content = re.sub(r'applicationId\s*=\s*"[^"]+"', f'applicationId = "{package_name}"', content, count=1)
    content = re.sub(r'versionCode\s*=\s*[^\n]+', f'versionCode = {version_code}', content, count=1)
    content = re.sub(r'versionName\s*=\s*[^\n]+', f'versionName = "{version}"', content, count=1)
    path.write_text(content, encoding="utf-8")
    _log(log_path, f"Injected package and version metadata into {path}")


def _write_tenant_config(path: Path, branding: Dict[str, object], log_path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    content = re.sub(
        r"const String embeddedTenantId = '.*?';",
        f"const String embeddedTenantId = '{_dart_single_quote(str(branding['tenant_id']))}';",
        content,
        count=1,
    )
    content = re.sub(
        r"String get embeddedTenantBackendUrl => .*?;",
        f"String get embeddedTenantBackendUrl => '{_dart_single_quote(str(branding['server_url']))}';",
        content,
        count=1,
    )
    content = re.sub(
        r"const String embeddedTenantApiToken = '.*?';",
        "const String embeddedTenantApiToken = '';",
        content,
        count=1,
    )
    path.write_text(content, encoding="utf-8")
    _log(log_path, f"Injected tenant bootstrap config into {path}")


def _write_pubspec_assets(path: Path, log_path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    required_assets = [
        "assets/branding/logo.png",
        "assets/branding/app_icon.png",
        "assets/branding/splash.png",
    ]
    missing_assets = [asset for asset in required_assets if asset not in content]
    if missing_assets:
        assets_block = "".join(f"    - {asset}\n" for asset in required_assets)
        if re.search(r"^  assets:\n", content, flags=re.MULTILINE):
            insert_at = content.index("  assets:\n") + len("  assets:\n")
            content = content[:insert_at] + assets_block + content[insert_at:]
        elif "  uses-material-design: true\n" in content:
            content = content.replace(
                "  uses-material-design: true\n",
                f"  uses-material-design: true\n  assets:\n{assets_block}",
                1,
            )
    path.write_text(content, encoding="utf-8")
    _log(log_path, f"Ensured branding assets are declared in {path}")


def _write_main_activity_package(source_path: Path, target_path: Path, package_name: str, log_path: Path) -> None:
    content = source_path.read_text(encoding="utf-8")
    updated = re.sub(r"^package\s+.+$", f"package {package_name}", content, count=1, flags=re.MULTILINE)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(updated, encoding="utf-8")
    if source_path.resolve() != target_path.resolve() and source_path.exists():
        source_path.unlink()
    _log(log_path, f"Updated MainActivity package path at {target_path}")


def _dart_single_quote(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")

def _tenant_branding_asset_path(tenant_id: str, filename: str) -> Path:
    return BACKEND_ROOT / "storage" / "branding" / str(tenant_id or "").strip() / filename


def _copy_branding_assets(workspace_dir: Path, branding: Dict[str, object], log_path: Path) -> None:
    assets_dir = workspace_dir / "assets" / "branding"
    assets_dir.mkdir(parents=True, exist_ok=True)
    tenant_id = str(branding.get("tenant_id") or "").strip()
    asset_map = {
        "logo.png": _tenant_branding_asset_path(tenant_id, "logo.png"),
        "app_icon.png": _tenant_branding_asset_path(tenant_id, "mobile_icon.png"),
        "splash.png": _tenant_branding_asset_path(tenant_id, "splash.png"),
    }
    for target_name, source_path in asset_map.items():
        if source_path.exists():
            shutil.copy2(source_path, assets_dir / target_name)
        else:
            _log(log_path, f"Branding asset {source_path} not found. Skipping {target_name}.")


def _replace_launcher_icons(workspace_dir: Path, tenant_id: str, logo_path: str, log_path: Path) -> None:
    generated_icon = _tenant_branding_asset_path(tenant_id, "mobile_icon.png")
    if generated_icon.exists():
        for icon_path in workspace_dir.glob("android/app/src/main/res/mipmap-*/ic_launcher.png"):
            shutil.copy2(generated_icon, icon_path)
        return
    if not logo_path or not logo_path.startswith("/assets/"):
        _log(log_path, "No branding logo file found. Keeping default launcher icon.")
        return
    source = BACKEND_ROOT / "data" / logo_path.lstrip("/").replace("/", os.sep)
    if not source.exists() or source.suffix.lower() != ".png":
        _log(log_path, f"Branding logo {source} is missing or not a PNG. Keeping default launcher icon.")
        return
    for icon_path in workspace_dir.glob("android/app/src/main/res/mipmap-*/ic_launcher.png"):
        shutil.copy2(source, icon_path)


def _powershell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_flutter_command(
    build_id: str,
    command: List[str],
    cwd: Path,
    log_path: Path,
) -> None:
    resolved_executable = _resolve_flutter_executable()
    android_sdk_dir = _resolve_android_sdk_dir()
    resolved_command = [resolved_executable, *command[1:]]
    _log(log_path, f"Running command: {_format_command_for_log(resolved_command)}")
    env = os.environ.copy()
    env.setdefault("FLUTTER_ROOT", _resolve_flutter_root())
    env.setdefault("CI", "true")
    env.setdefault("FLUTTER_SUPPRESS_ANALYTICS", "true")
    env.setdefault("PUB_ENVIRONMENT", "flutter_cli:mobile_builder")
    if android_sdk_dir:
        env.setdefault("ANDROID_SDK_ROOT", android_sdk_dir)
        env.setdefault("ANDROID_HOME", android_sdk_dir)
    try:
        process = subprocess.Popen(
            resolved_command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            bufsize=1,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Flutter executable could not be started.") from exc
    with ACTIVE_PROCESSES_LOCK:
        ACTIVE_PROCESSES[build_id] = process
    reader_errors: List[Exception] = []

    def _drain_output(stream_name: str, stream) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                if line:
                    _log(log_path, f"[{stream_name}] {line.rstrip()}")
        except Exception as exc:
            reader_errors.append(exc)

    stdout_thread = threading.Thread(
        target=_drain_output,
        args=("stdout", process.stdout),
        name=f"mobile-build-stdout-{build_id}",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_output,
        args=("stderr", process.stderr),
        name=f"mobile-build-stderr-{build_id}",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    cancelled = False
    try:
        while process.poll() is None:
            if _is_cancellation_requested(build_id):
                cancelled = True
                try:
                    process.terminate()
                except Exception:
                    pass
            time.sleep(0.2)
        process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
    finally:
        with ACTIVE_PROCESSES_LOCK:
            ACTIVE_PROCESSES.pop(build_id, None)
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()
    if reader_errors:
        _log(log_path, f"Output reader error: {reader_errors[0]}")
    if cancelled or _is_cancellation_requested(build_id):
        raise BuildCancelledError("Build cancelled by user.")
    if process.returncode != 0:
        raise RuntimeError(f"{_format_command_for_log(resolved_command)} failed with exit code {process.returncode}.")


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{utc_now_iso()} {message.rstrip()}\n")


def _format_command_for_log(command: List[str]) -> str:
    return " ".join(_powershell_quote(part) if " " in str(part) else str(part) for part in command)
