from __future__ import annotations

from typing import Dict


def render_subscription_renewal_email(
    *,
    admin_name: str,
    app_name: str,
    renewal_url: str,
    download_url: str,
    subscription_end_date: str,
) -> Dict[str, str]:
    subject = f"{app_name} subscription renewal reminder"
    html = f"""
    <html>
      <body style="font-family:Arial,sans-serif;background:#07141E;color:#F2F8FF;padding:24px;">
        <div style="max-width:640px;margin:0 auto;background:#0D1E2B;border-radius:18px;padding:24px;border:1px solid rgba(255,255,255,0.08);">
          <p style="color:#7EE3AF;text-transform:uppercase;letter-spacing:0.12em;font-size:12px;">White-label operations</p>
          <h1 style="margin:0 0 12px;">Subscription renewal reminder</h1>
          <p>Hello {admin_name or "Admin"},</p>
          <p>Your {app_name} subscription is due to expire on <strong>{subscription_end_date}</strong>.</p>
          <p>Please renew now to keep desktop administration, mobile publishing, and server binding active.</p>
          <p>
            <a href="{renewal_url}" style="display:inline-block;background:#39d98a;color:#041219;padding:12px 18px;border-radius:12px;text-decoration:none;font-weight:700;">Renew subscription</a>
          </p>
          <p>If you also need the latest desktop installer, use the link below:</p>
          <p><a href="{download_url}">{download_url}</a></p>
        </div>
      </body>
    </html>
    """.strip()
    text = (
        f"{app_name} subscription renewal reminder\n\n"
        f"Hello {admin_name or 'Admin'},\n\n"
        f"Your subscription is due to expire on {subscription_end_date}.\n"
        f"Renew here: {renewal_url}\n"
        f"Latest desktop download: {download_url}\n"
    )
    return {"subject": subject, "html": html, "text": text}
