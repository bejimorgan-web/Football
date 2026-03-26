import os
from typing import Optional, Tuple

from pydantic import BaseModel

from app.config import DEFAULT_API_URL

DEFAULT_API_BASE_URL = DEFAULT_API_URL
MODE = (os.getenv("MODE") or "development").strip().lower() or "development"


class IPTVSettings(BaseModel):
    xtream_server_url: Optional[str] = None
    xtream_username: Optional[str] = None
    xtream_password: Optional[str] = None
    m3u_playlist_url: Optional[str] = None
    cache_ttl_seconds: int = 300


class AdminAuthSettings(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None


class BackupSettings(BaseModel):
    schedule: str = "0 3 * * *"
    path: str = ""
    retention: int = 7
    cloud_backup_enabled: bool = False
    s3_bucket: Optional[str] = None
    s3_prefix: str = "football-iptv-backups"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: Optional[str] = None


class EmailSettings(BaseModel):
    schedule: str = "0 9 * * *"
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from_email: Optional[str] = None
    smtp_use_tls: bool = True
    platform_base_url: str = ""
    desktop_download_url: str = ""


class PublicApiSettings(BaseModel):
    api_base_url: str = DEFAULT_API_BASE_URL


def is_development_mode() -> bool:
    return MODE == "development"


def load_settings_from_env() -> IPTVSettings:
    return IPTVSettings(
        xtream_server_url=os.getenv("XTREAM_SERVER_URL") or None,
        xtream_username=os.getenv("XTREAM_USERNAME") or None,
        xtream_password=os.getenv("XTREAM_PASSWORD") or None,
        m3u_playlist_url=os.getenv("M3U_PLAYLIST_URL") or None,
        cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "300")),
    )


def load_admin_settings_from_env() -> AdminAuthSettings:
    return AdminAuthSettings(
        username=os.getenv("ADMIN_USERNAME") or None,
        password=os.getenv("ADMIN_PASSWORD") or None,
    )


def load_backup_settings_from_env() -> BackupSettings:
    return BackupSettings(
        schedule=os.getenv("BACKUP_SCHEDULE", "0 3 * * *"),
        path=os.getenv("BACKUP_PATH", ""),
        retention=int(os.getenv("BACKUP_RETENTION", "7")),
        cloud_backup_enabled=os.getenv("CLOUD_BACKUP_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        s3_bucket=os.getenv("S3_BUCKET") or None,
        s3_prefix=os.getenv("S3_PREFIX", "football-iptv-backups").strip() or "football-iptv-backups",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID") or None,
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY") or None,
        aws_region=os.getenv("AWS_REGION") or None,
    )


def load_email_settings_from_env() -> EmailSettings:
    return EmailSettings(
        schedule=os.getenv("SUBSCRIPTION_REMINDER_SCHEDULE", "0 9 * * *"),
        smtp_host=os.getenv("SMTP_HOST") or None,
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME") or None,
        smtp_password=os.getenv("SMTP_PASSWORD") or None,
        smtp_from_email=os.getenv("SMTP_FROM_EMAIL") or None,
        smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"},
        platform_base_url=os.getenv("PLATFORM_BASE_URL", "").strip(),
        desktop_download_url=os.getenv("DESKTOP_DOWNLOAD_URL", "").strip(),
    )


def load_public_api_settings_from_env() -> PublicApiSettings:
    return PublicApiSettings(
        api_base_url=os.getenv("API_BASE_URL", DEFAULT_API_BASE_URL).strip() or DEFAULT_API_BASE_URL,
    )


def validate_settings(settings: IPTVSettings) -> Tuple[bool, str]:
    has_m3u = bool(settings.m3u_playlist_url)
    has_xtream_any = any(
        [settings.xtream_server_url, settings.xtream_username, settings.xtream_password]
    )

    if settings.cache_ttl_seconds <= 0:
        return False, "cache_ttl_seconds must be greater than 0."

    if has_m3u and has_xtream_any:
        return False, "Provide either M3U playlist URL or Xtream credentials, not both."

    if has_m3u:
        return True, ""

    if has_xtream_any:
        if not (
            settings.xtream_server_url
            and settings.xtream_username
            and settings.xtream_password
        ):
            return (
                False,
                "Xtream configuration requires server URL, username, and password.",
            )
        return True, ""

    return False, "No configuration provided."
