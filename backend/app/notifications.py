from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Dict, List, Optional

from app.email_templates import render_subscription_renewal_email
from app.settings import EmailSettings
from app.storage import admins_with_expiring_subscriptions, log_email_event, utc_now_iso

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
except Exception:  # pragma: no cover - optional dependency handling
    BackgroundScheduler = None
    CronTrigger = None

_notification_scheduler = None


def _send_email(settings: EmailSettings, *, recipient: str, subject: str, html: str, text: str) -> str:
    if not settings.smtp_host or not settings.smtp_from_email:
        return "logged-only"

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_username and settings.smtp_password:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
    return "sent"


def run_subscription_notification_check(settings: EmailSettings) -> Dict[str, object]:
    items: List[Dict[str, object]] = []
    renewal_root = settings.platform_base_url.rstrip("/")
    download_url = settings.desktop_download_url.rstrip("/")
    for admin in admins_with_expiring_subscriptions(within_days=7):
        template = render_subscription_renewal_email(
            admin_name=str(admin.get("name") or "Admin"),
            app_name=str((admin.get("branding_info") or {}).get("app_name") or admin.get("name") or "Football Streaming"),
            renewal_url=f"{renewal_root}/renew?admin_id={admin.get('admin_id')}" if renewal_root else "Renewal link not configured",
            download_url=download_url or "Download link not configured",
            subscription_end_date=str(admin.get("subscription_end_date") or admin.get("subscription_end") or ""),
        )
        status = "logged"
        detail = "SMTP is not configured."
        try:
            status = _send_email(
                settings,
                recipient=str(admin.get("email") or ""),
                subject=template["subject"],
                html=template["html"],
                text=template["text"],
            )
            detail = f"Reminder processed at {utc_now_iso()}."
        except Exception as exc:  # pragma: no cover - depends on SMTP availability
            status = "failed"
            detail = str(exc)
        items.append(
            log_email_event(
                admin_id=str(admin.get("admin_id") or ""),
                tenant_id=str(admin.get("tenant_id") or ""),
                email=str(admin.get("email") or ""),
                subject=template["subject"],
                status=status,
                detail=detail,
            )
        )
    return {"items": items, "count": len(items)}


def start_notification_scheduler(settings: EmailSettings) -> Optional[str]:
    global _notification_scheduler
    if BackgroundScheduler is None or CronTrigger is None:
        return "APScheduler is not installed. Subscription reminder emails are disabled."
    if _notification_scheduler is not None and _notification_scheduler.running:
        return None
    try:
        trigger = CronTrigger.from_crontab(settings.schedule)
    except ValueError as exc:
        return f"Invalid SUBSCRIPTION_REMINDER_SCHEDULE: {exc}"

    _notification_scheduler = BackgroundScheduler()
    _notification_scheduler.add_job(
        run_subscription_notification_check,
        trigger=trigger,
        args=[settings],
        id="subscription-reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _notification_scheduler.start()
    return None


def stop_notification_scheduler() -> None:
    global _notification_scheduler
    if _notification_scheduler is None:
        return
    _notification_scheduler.shutdown(wait=False)
    _notification_scheduler = None
