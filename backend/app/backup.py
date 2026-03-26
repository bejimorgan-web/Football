from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from app.settings import BackupSettings
from app.storage import DATA_DIR

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
except Exception:  # pragma: no cover - optional dependency handling
    BackgroundScheduler = None
    CronTrigger = None

BACKEND_DIR = DATA_DIR.parent
DEFAULT_BACKUP_DIR = BACKEND_DIR / "backups"
BACKUP_LOGS_PATH = DATA_DIR / "backup_logs.json"
BACKUP_ARCHIVE_PREFIX = "backup_"
MAX_BACKUP_LOGS = 200

_backup_scheduler = None


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def ensure_backup_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not BACKUP_LOGS_PATH.exists():
        save_backup_logs([])


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_backup_logs() -> List[Dict[str, object]]:
    payload = _read_json(BACKUP_LOGS_PATH, [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def save_backup_logs(logs: List[Dict[str, object]]) -> None:
    _write_json(BACKUP_LOGS_PATH, logs[-MAX_BACKUP_LOGS:])


def _backup_directory(settings: BackupSettings) -> Path:
    configured = str(settings.path or "").strip()
    target = Path(configured) if configured else DEFAULT_BACKUP_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def _timestamp_label() -> str:
    return utc_now().strftime("%Y%m%d_%H%M%S")


def _append_log(entry: Dict[str, object]) -> None:
    logs = load_backup_logs()
    logs.append(entry)
    save_backup_logs(logs)


def list_backup_files(settings: BackupSettings) -> List[Dict[str, object]]:
    backup_dir = _backup_directory(settings)
    items: List[Dict[str, object]] = []
    for file_path in sorted(backup_dir.glob(f"{BACKUP_ARCHIVE_PREFIX}*.zip"), reverse=True):
        stat = file_path.stat()
        items.append(
            {
                "name": file_path.name,
                "path": str(file_path.resolve()),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            }
        )
    return items


def cleanup_old_backups(settings: BackupSettings) -> List[str]:
    retention = max(1, int(settings.retention or 1))
    backups = list(_backup_directory(settings).glob(f"{BACKUP_ARCHIVE_PREFIX}*.zip"))
    backups.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    removed: List[str] = []
    for file_path in backups[retention:]:
        try:
            file_path.unlink()
            removed.append(str(file_path.resolve()))
        except OSError:
            continue
    return removed


def _make_archive(archive_base: Path) -> Path:
    BACKEND_DIR.mkdir(parents=True, exist_ok=True)
    staging_root = BACKEND_DIR / f".backup-tmp-{uuid4().hex}"
    try:
        snapshot_dir = staging_root / "data"
        shutil.copytree(DATA_DIR, snapshot_dir)
        archive_path = shutil.make_archive(
            base_name=str(archive_base),
            format="zip",
            root_dir=str(staging_root),
            base_dir="data",
        )
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    return Path(archive_path)


def upload_backup_to_s3(archive_path: Path, settings: BackupSettings) -> Dict[str, object]:
    if not settings.cloud_backup_enabled:
        return {"enabled": False, "uploaded": False, "location": None}
    if not settings.s3_bucket:
        raise ValueError("Cloud backup is enabled but S3_BUCKET is not configured.")

    try:
        import boto3
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError("boto3 is required for cloud backups. Install it in backend/requirements.txt.") from exc

    session_kwargs = {}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
        session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if settings.aws_region:
        session_kwargs["region_name"] = settings.aws_region

    client = boto3.client("s3", **session_kwargs)
    key_prefix = str(settings.s3_prefix or "").strip().strip("/")
    object_key = f"{key_prefix}/{archive_path.name}" if key_prefix else archive_path.name
    extra_args = {"ServerSideEncryption": "AES256"}
    client.upload_file(str(archive_path), settings.s3_bucket, object_key, ExtraArgs=extra_args)
    return {
        "enabled": True,
        "uploaded": True,
        "location": f"s3://{settings.s3_bucket}/{object_key}",
    }


def create_backup(settings: BackupSettings) -> Dict[str, object]:
    ensure_backup_storage()
    backup_dir = _backup_directory(settings)
    archive_name = f"{BACKUP_ARCHIVE_PREFIX}{_timestamp_label()}"
    archive_base = backup_dir / archive_name
    started_at = utc_now_iso()
    log_entry: Dict[str, object] = {
        "id": uuid4().hex,
        "started_at": started_at,
        "finished_at": None,
        "success": False,
        "archive_path": None,
        "cloud_enabled": bool(settings.cloud_backup_enabled),
        "cloud_uploaded": False,
        "cloud_location": None,
        "removed_backups": [],
        "error": "",
    }

    try:
        archive_path = _make_archive(archive_base)
        log_entry["archive_path"] = str(archive_path.resolve())

        upload_result = upload_backup_to_s3(archive_path, settings)
        log_entry["cloud_uploaded"] = bool(upload_result.get("uploaded"))
        log_entry["cloud_location"] = upload_result.get("location")

        removed_backups = cleanup_old_backups(settings)
        log_entry["removed_backups"] = removed_backups
        log_entry["success"] = True
        log_entry["finished_at"] = utc_now_iso()
        _append_log(log_entry)

        return {
            "status": "ok",
            "archive_path": str(archive_path.resolve()),
            "archive_name": archive_path.name,
            "backup_dir": str(backup_dir.resolve()),
            "removed_backups": removed_backups,
            "cloud": upload_result,
            "started_at": started_at,
            "finished_at": log_entry["finished_at"],
            "included_paths": [str(DATA_DIR.resolve())],
        }
    except Exception as exc:
        log_entry["finished_at"] = utc_now_iso()
        log_entry["error"] = str(exc)
        _append_log(log_entry)
        return {
            "status": "error",
            "archive_path": log_entry["archive_path"],
            "backup_dir": str(backup_dir.resolve()),
            "error": str(exc),
            "started_at": started_at,
            "finished_at": log_entry["finished_at"],
            "included_paths": [str(DATA_DIR.resolve())],
        }


def restore_backup(archive_file: str) -> Dict[str, object]:
    ensure_backup_storage()
    archive_path = Path(str(archive_file or "").strip())
    started_at = utc_now_iso()
    log_entry: Dict[str, object] = {
        "id": uuid4().hex,
        "started_at": started_at,
        "finished_at": None,
        "success": False,
        "archive_path": str(archive_path.resolve()) if archive_path.exists() else str(archive_path),
        "cloud_enabled": False,
        "cloud_uploaded": False,
        "cloud_location": None,
        "removed_backups": [],
        "error": "",
        "operation": "restore",
    }

    try:
        if not archive_path.exists():
            raise FileNotFoundError("Backup archive not found.")
        BACKEND_DIR.mkdir(parents=True, exist_ok=True)
        temp_root = BACKEND_DIR / f".restore-tmp-{uuid4().hex}"
        try:
            temp_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive_path, "r") as archive:
                archive.extractall(temp_root)

            extracted_data_dir = temp_root / "data"
            if not extracted_data_dir.exists():
                raise ValueError("Backup archive does not contain a data directory.")

            if DATA_DIR.exists():
                shutil.rmtree(DATA_DIR)
            shutil.copytree(extracted_data_dir, DATA_DIR)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        log_entry["success"] = True
        log_entry["finished_at"] = utc_now_iso()
        _append_log(log_entry)
        return {
            "status": "ok",
            "operation": "restore",
            "archive_path": str(archive_path.resolve()),
            "restored_to": str(DATA_DIR.resolve()),
            "started_at": started_at,
            "finished_at": log_entry["finished_at"],
        }
    except Exception as exc:
        log_entry["finished_at"] = utc_now_iso()
        log_entry["error"] = str(exc)
        _append_log(log_entry)
        return {
            "status": "error",
            "operation": "restore",
            "archive_path": str(archive_path),
            "restored_to": str(DATA_DIR.resolve()),
            "error": str(exc),
            "started_at": started_at,
            "finished_at": log_entry["finished_at"],
        }


def get_backup_status(settings: BackupSettings) -> Dict[str, object]:
    ensure_backup_storage()
    logs = load_backup_logs()
    last_log = logs[-1] if logs else None
    return {
        "configured_schedule": settings.schedule,
        "backup_path": str(_backup_directory(settings).resolve()),
        "retention": max(1, int(settings.retention or 1)),
        "cloud_backup_enabled": bool(settings.cloud_backup_enabled),
        "s3_bucket": settings.s3_bucket,
        "last_backup": last_log,
        "recent_logs": logs[-20:],
        "backups": list_backup_files(settings),
        "included_paths": [str(DATA_DIR.resolve())],
    }


def _run_scheduled_backup(settings: BackupSettings) -> None:
    create_backup(settings)


def start_backup_scheduler(settings: BackupSettings) -> Optional[str]:
    global _backup_scheduler

    ensure_backup_storage()
    if BackgroundScheduler is None or CronTrigger is None:
        _append_log(
            {
                "id": uuid4().hex,
                "started_at": utc_now_iso(),
                "finished_at": utc_now_iso(),
                "success": False,
                "archive_path": None,
                "cloud_enabled": bool(settings.cloud_backup_enabled),
                "cloud_uploaded": False,
                "cloud_location": None,
                "removed_backups": [],
                "error": "APScheduler is not installed. Automatic backups are disabled.",
            }
        )
        return "APScheduler is not installed. Automatic backups are disabled."

    if _backup_scheduler is not None and _backup_scheduler.running:
        return None

    try:
        trigger = CronTrigger.from_crontab(settings.schedule)
    except ValueError as exc:
        _append_log(
            {
                "id": uuid4().hex,
                "started_at": utc_now_iso(),
                "finished_at": utc_now_iso(),
                "success": False,
                "archive_path": None,
                "cloud_enabled": bool(settings.cloud_backup_enabled),
                "cloud_uploaded": False,
                "cloud_location": None,
                "removed_backups": [],
                "error": f"Invalid BACKUP_SCHEDULE: {exc}",
            }
        )
        return f"Invalid BACKUP_SCHEDULE: {exc}"

    _backup_scheduler = BackgroundScheduler()
    _backup_scheduler.add_job(
        _run_scheduled_backup,
        trigger=trigger,
        args=[settings],
        id="automatic-backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _backup_scheduler.start()
    return None


def stop_backup_scheduler() -> None:
    global _backup_scheduler
    if _backup_scheduler is None:
        return
    _backup_scheduler.shutdown(wait=False)
    _backup_scheduler = None


def run_backup_cli() -> int:
    from app.settings import load_backup_settings_from_env

    parser = argparse.ArgumentParser(description="Football IPTV backup utility")
    parser.add_argument("--action", choices=["create", "status", "list", "restore"], default="create")
    parser.add_argument("--file", default="", help="Backup archive path used for restore.")
    args = parser.parse_args()

    settings = load_backup_settings_from_env()
    if args.action == "create":
        result = create_backup(settings)
    elif args.action == "status":
        result = get_backup_status(settings)
    elif args.action == "list":
        result = {"status": "ok", "backups": list_backup_files(settings)}
    else:
        result = restore_backup(args.file)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") in {None, "ok"} else 1


if __name__ == "__main__":
    raise SystemExit(run_backup_cli())
