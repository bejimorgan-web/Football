from __future__ import annotations

import logging
import os
import socket
import time

import httpx

from app.api_config import ensure_api_config_storage
from app.backup import ensure_backup_storage
from app.branding_engine import ensure_branding_storage
from app.env_loader import load_backend_env
from app.logo_utils import ensure_static_logo_storage
import app.mobile_builder as mobile_builder
from app.mobile_builder import (
    BuildCancelledError,
    build_tenant_apk_in_docker,
    ensure_mobile_builder_storage,
    mobile_build_worker_enabled,
    start_mobile_build_worker,
    stop_mobile_build_worker,
)
from app.storage import ensure_storage_files, flush_audit_logs
from app.update_service import ensure_update_storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("football_iptv.mobile_builder_worker")

load_backend_env(worker=True)


def _prepare_runtime_storage() -> None:
    ensure_storage_files()
    ensure_backup_storage()
    ensure_update_storage()
    ensure_mobile_builder_storage()
    ensure_branding_storage()
    ensure_api_config_storage()
    ensure_static_logo_storage()


def _remote_worker_api_url() -> str:
    return str(os.environ.get("MOBILE_BUILD_WORKER_API_URL") or "").strip().rstrip("/")


def _remote_worker_token() -> str:
    return str(os.environ.get("MOBILE_BUILD_WORKER_TOKEN") or "").strip()


def _remote_worker_id() -> str:
    configured = str(os.environ.get("MOBILE_BUILD_WORKER_ID") or "").strip()
    if configured:
        return configured
    return f"{socket.gethostname()}-mobile-builder"


def _run_remote_worker() -> None:
    api_url = _remote_worker_api_url()
    token = _remote_worker_token()
    worker_id = _remote_worker_id()
    logger.info("Mobile build worker running in remote mode against %s", api_url)
    headers = {"X-Mobile-Worker-Token": token}
    with httpx.Client(base_url=api_url, headers=headers, timeout=60.0) as client:
        while True:
            try:
                response = client.post("/mobile/worker/claim", json={"worker_id": worker_id})
                response.raise_for_status()
                job = (response.json() or {}).get("job")
                if not isinstance(job, dict):
                    time.sleep(2)
                    continue
                _process_remote_job(client, job)
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.exception("Remote mobile build worker poll failed.")
                time.sleep(5)


def _process_remote_job(client: httpx.Client, job: dict) -> None:
    build_id = str(job.get("build_id") or "")
    log_path = mobile_builder.BUILD_LOGS_DIR / f"{build_id}.log"
    tenant_data = {
        "tenant_id": str(job.get("tenant_id") or ""),
        "app_name": str(job.get("app_name") or ""),
        "package_name": str(job.get("package_name") or ""),
        "server_url": str(job.get("server_url") or ""),
        "primary_color": str(job.get("primary_color") or ""),
        "secondary_color": str(job.get("secondary_color") or ""),
        "logo_file": str(job.get("logo_file") or ""),
        "splash_screen": str(job.get("splash_screen") or ""),
    }
    original_log = mobile_builder._log
    original_cancel = mobile_builder._is_cancellation_requested

    def remote_log(path, message):
        original_log(path, message)
        try:
            client.post(f"/mobile/worker/build/{build_id}/update", json={"log": str(message)})
        except Exception:
            logger.exception("Failed to stream remote build log for %s", build_id)

    def remote_cancel_requested(current_build_id: str) -> bool:
        try:
            response = client.get(f"/mobile/worker/build/{current_build_id}")
            response.raise_for_status()
            current_job = response.json() or {}
        except Exception:
            return False
        return str(current_job.get("status") or "").strip().lower() in {"cancelling", "cancelled"}

    mobile_builder._log = remote_log
    mobile_builder._is_cancellation_requested = remote_cancel_requested
    try:
        client.post(f"/mobile/worker/build/{build_id}/update", json={"status": "building", "progress": 15, "error": ""})
        result = build_tenant_apk_in_docker(
            build_id=build_id,
            tenant_data=tenant_data,
            version=str(job.get("version") or "1.0.0"),
            admin_id=str(job.get("admin_id") or ""),
            log_path=log_path,
        )
        client.post(f"/mobile/worker/build/{build_id}/complete", json=result)
    except BuildCancelledError as exc:
        client.post(f"/mobile/worker/build/{build_id}/fail", json={"status": "cancelled", "error": str(exc)})
    except Exception as exc:
        logger.exception("Remote build failed for %s", build_id)
        client.post(f"/mobile/worker/build/{build_id}/fail", json={"status": "failed", "error": str(exc)})
    finally:
        mobile_builder._log = original_log
        mobile_builder._is_cancellation_requested = original_cancel


def main() -> None:
    _prepare_runtime_storage()
    logger.info("Mobile build worker process starting.")
    worker_enabled = mobile_build_worker_enabled()
    logger.info("MOBILE_BUILD_WORKER_ENABLED=%s", worker_enabled)
    if not worker_enabled:
        logger.info("Mobile build worker is disabled by configuration. Exiting without starting worker loops.")
        return
    if _remote_worker_api_url() and _remote_worker_token():
        _run_remote_worker()
        return
    start_mobile_build_worker()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Mobile build worker interrupted, shutting down.")
    finally:
        stop_mobile_build_worker()
        flush_audit_logs(force=True)


if __name__ == "__main__":
    main()


import os
print("DATABASE_URL:", os.getenv("MOBILE_BUILD_DATABASE_URL"))
