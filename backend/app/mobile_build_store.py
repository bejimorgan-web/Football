from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - handled by runtime config
    psycopg = None
    dict_row = None

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data"
MOBILE_BUILD_DB_PATH = Path(
    os.environ.get("MOBILE_BUILD_DB_PATH", str(DATA_DIR / "mobile_builds.db")).strip()
    or (DATA_DIR / "mobile_builds.db")
)
MOBILE_BUILD_DATABASE_URL = str(
    os.environ.get("MOBILE_BUILD_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or ""
).strip()

_DB_LOCK = threading.Lock()
_POSTGRES_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg"}


def _database_backend() -> str:
    parsed = urlparse(MOBILE_BUILD_DATABASE_URL)
    if parsed.scheme.lower() in _POSTGRES_SCHEMES:
        return "postgres"
    return "sqlite"


def _normalized_postgres_dsn() -> str:
    if _database_backend() != "postgres":
        return ""
    if MOBILE_BUILD_DATABASE_URL.startswith("postgresql+psycopg://"):
        return "postgresql://" + MOBILE_BUILD_DATABASE_URL.split("://", 1)[1]
    return MOBILE_BUILD_DATABASE_URL


def _sqlite_connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(MOBILE_BUILD_DB_PATH, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def _postgres_connect():
    if psycopg is None:
        raise RuntimeError(
            "psycopg is required when MOBILE_BUILD_DATABASE_URL points to PostgreSQL. "
            "Install psycopg[binary] in the backend environment."
        )
    return psycopg.connect(_normalized_postgres_dsn(), autocommit=True, row_factory=dict_row)


def _connect():
    if _database_backend() == "postgres":
        return _postgres_connect()
    return _sqlite_connect()


def _create_table_sql() -> str:
    text_type = "TEXT"
    integer_type = "INTEGER"
    return f"""
        CREATE TABLE IF NOT EXISTS mobile_build_jobs (
            build_id {text_type} PRIMARY KEY,
            admin_id {text_type} NOT NULL,
            tenant_id {text_type} NOT NULL,
            status {text_type} NOT NULL,
            progress {integer_type} NOT NULL DEFAULT 0,
            created_at {text_type} NOT NULL,
            updated_at {text_type} NOT NULL,
            completed_at {text_type},
            version {text_type} NOT NULL,
            app_name {text_type} NOT NULL,
            package_name {text_type} NOT NULL,
            server_url {text_type} NOT NULL,
            primary_color {text_type} NOT NULL,
            secondary_color {text_type} NOT NULL,
            logo_file {text_type} NOT NULL,
            splash_screen {text_type} NOT NULL,
            artifact_name {text_type} NOT NULL DEFAULT '',
            artifact_path {text_type} NOT NULL DEFAULT '',
            artifact_storage {text_type} NOT NULL DEFAULT 'local',
            artifact_key {text_type} NOT NULL DEFAULT '',
            artifact_url {text_type} NOT NULL DEFAULT '',
            error {text_type} NOT NULL DEFAULT '',
            logs {text_type} NOT NULL DEFAULT '',
            worker_id {text_type} NOT NULL DEFAULT ''
        )
    """


def ensure_mobile_build_store() -> None:
    with _DB_LOCK:
        connection = _connect()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(_create_table_sql())
            finally:
                cursor.close()
        finally:
            connection.close()


def _row_to_job(row: Any) -> Optional[Dict[str, object]]:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def _execute_fetchone(query: str, params: tuple[Any, ...] = ()) -> Optional[Dict[str, object]]:
    ensure_mobile_build_store()
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(query, params)
            return _row_to_job(cursor.fetchone())
        finally:
            cursor.close()
    finally:
        connection.close()


def _execute_fetchall(query: str, params: tuple[Any, ...] = ()) -> List[Dict[str, object]]:
    ensure_mobile_build_store()
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()
    finally:
        connection.close()


def create_mobile_build_job(job: Dict[str, object]) -> Dict[str, object]:
    ensure_mobile_build_store()
    params = (
        str(job.get("build_id") or ""),
        str(job.get("admin_id") or ""),
        str(job.get("tenant_id") or ""),
        str(job.get("status") or "queued"),
        int(job.get("progress") or 0),
        str(job.get("created_at") or ""),
        str(job.get("updated_at") or ""),
        str(job.get("completed_at") or "") or None,
        str(job.get("version") or ""),
        str(job.get("app_name") or ""),
        str(job.get("package_name") or ""),
        str(job.get("server_url") or ""),
        str(job.get("primary_color") or ""),
        str(job.get("secondary_color") or ""),
        str(job.get("logo_file") or ""),
        str(job.get("splash_screen") or ""),
        str(job.get("artifact_name") or ""),
        str(job.get("artifact_path") or ""),
        str(job.get("artifact_storage") or "local"),
        str(job.get("artifact_key") or ""),
        str(job.get("artifact_url") or ""),
        str(job.get("error") or ""),
        str(job.get("logs") or ""),
        str(job.get("worker_id") or ""),
    )
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            if _database_backend() == "postgres":
                cursor.execute(
                    """
                    INSERT INTO mobile_build_jobs (
                        build_id, admin_id, tenant_id, status, progress, created_at, updated_at,
                        completed_at, version, app_name, package_name, server_url, primary_color,
                        secondary_color, logo_file, splash_screen, artifact_name, artifact_path,
                        artifact_storage, artifact_key, artifact_url, error, logs, worker_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    params,
                )
                cursor.execute("SELECT * FROM mobile_build_jobs WHERE build_id = %s", (str(job.get("build_id") or ""),))
            else:
                cursor.execute(
                    """
                    INSERT INTO mobile_build_jobs (
                        build_id, admin_id, tenant_id, status, progress, created_at, updated_at,
                        completed_at, version, app_name, package_name, server_url, primary_color,
                        secondary_color, logo_file, splash_screen, artifact_name, artifact_path,
                        artifact_storage, artifact_key, artifact_url, error, logs, worker_id
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    params,
                )
                cursor.execute("SELECT * FROM mobile_build_jobs WHERE build_id = ?", (str(job.get("build_id") or ""),))
            return _row_to_job(cursor.fetchone()) or dict(job)
        finally:
            cursor.close()
    finally:
        connection.close()


def list_mobile_build_jobs(*, admin_id: Optional[str] = None) -> List[Dict[str, object]]:
    if admin_id:
        placeholder = "%s" if _database_backend() == "postgres" else "?"
        return _execute_fetchall(
            f"SELECT * FROM mobile_build_jobs WHERE admin_id = {placeholder} ORDER BY created_at DESC",
            (str(admin_id),),
        )
    return _execute_fetchall("SELECT * FROM mobile_build_jobs ORDER BY created_at DESC")


def get_mobile_build_job(build_id: str) -> Optional[Dict[str, object]]:
    placeholder = "%s" if _database_backend() == "postgres" else "?"
    return _execute_fetchone(
        f"SELECT * FROM mobile_build_jobs WHERE build_id = {placeholder}",
        (str(build_id),),
    )


def update_mobile_build_job(build_id: str, patch: Dict[str, object]) -> Dict[str, object]:
    ensure_mobile_build_store()
    if not patch:
        job = get_mobile_build_job(build_id)
        if job is None:
            raise ValueError("Build job not found.")
        return job
    assignments: List[str] = []
    values: List[Any] = []
    placeholder = "%s" if _database_backend() == "postgres" else "?"
    for key, value in patch.items():
        assignments.append(f"{key} = {placeholder}")
        values.append(value)
    values.append(str(build_id))
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"UPDATE mobile_build_jobs SET {', '.join(assignments)} WHERE build_id = {placeholder}",
                tuple(values),
            )
            if cursor.rowcount == 0:
                raise ValueError("Build job not found.")
            cursor.execute(
                f"SELECT * FROM mobile_build_jobs WHERE build_id = {placeholder}",
                (str(build_id),),
            )
            return _row_to_job(cursor.fetchone()) or {}
        finally:
            cursor.close()
    finally:
        connection.close()


def append_mobile_build_log(build_id: str, message: str) -> None:
    ensure_mobile_build_store()
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            if _database_backend() == "postgres":
                cursor.execute("SELECT logs FROM mobile_build_jobs WHERE build_id = %s", (str(build_id),))
            else:
                cursor.execute("SELECT logs FROM mobile_build_jobs WHERE build_id = ?", (str(build_id),))
            row = cursor.fetchone()
            if row is None:
                return
            existing = str((row["logs"] if isinstance(row, dict) else row["logs"]) or "")
            if _database_backend() == "postgres":
                cursor.execute(
                    "UPDATE mobile_build_jobs SET logs = %s WHERE build_id = %s",
                    (existing + message, str(build_id)),
                )
            else:
                cursor.execute(
                    "UPDATE mobile_build_jobs SET logs = ? WHERE build_id = ?",
                    (existing + message, str(build_id)),
                )
        finally:
            cursor.close()
    finally:
        connection.close()


def claim_next_mobile_build_job(worker_id: str, *, updated_at: str) -> Optional[Dict[str, object]]:
    ensure_mobile_build_store()
    with _DB_LOCK:
        connection = _connect()
        try:
            if _database_backend() == "postgres":
                connection.autocommit = False
                try:
                    cursor = connection.cursor()
                    try:
                        cursor.execute(
                            """
                            SELECT build_id
                            FROM mobile_build_jobs
                            WHERE status = 'queued'
                            ORDER BY created_at ASC
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                            """
                        )
                        row = cursor.fetchone()
                        if row is None:
                            connection.commit()
                            return None
                        build_id = str(row["build_id"])
                        cursor.execute(
                            """
                            UPDATE mobile_build_jobs
                            SET status = %s, worker_id = %s, updated_at = %s, error = %s
                            WHERE build_id = %s
                            """,
                            ("building", str(worker_id), str(updated_at), "", build_id),
                        )
                        cursor.execute("SELECT * FROM mobile_build_jobs WHERE build_id = %s", (build_id,))
                        claimed = cursor.fetchone()
                        connection.commit()
                        return _row_to_job(claimed)
                    finally:
                        cursor.close()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.autocommit = True

            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT build_id FROM mobile_build_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None
            build_id = str(row["build_id"])
            connection.execute(
                """
                UPDATE mobile_build_jobs
                SET status = ?, worker_id = ?, updated_at = ?, error = ?
                WHERE build_id = ?
                """,
                ("building", str(worker_id), str(updated_at), "", build_id),
            )
            claimed = connection.execute(
                "SELECT * FROM mobile_build_jobs WHERE build_id = ?",
                (build_id,),
            ).fetchone()
            connection.execute("COMMIT")
            return _row_to_job(claimed)
        except Exception:
            if _database_backend() == "postgres":
                try:
                    connection.rollback()
                except Exception:
                    pass
            else:
                try:
                    connection.execute("ROLLBACK")
                except Exception:
                    pass
            raise
        finally:
            connection.close()
