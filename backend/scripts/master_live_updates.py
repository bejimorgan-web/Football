from __future__ import annotations

import json
import os
import socket
from typing import Any, Dict

import requests

LOCAL_BACKEND_URL = "http://127.0.0.1:8000"


def _strip_trailing_slash(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def resolve_backend_url() -> str:
    configured = _strip_trailing_slash(os.getenv("BACKEND_URL", ""))
    if configured:
        return configured

    try:
        response = requests.get(f"{LOCAL_BACKEND_URL}/api/config", timeout=5)
        response.raise_for_status()
        payload = response.json()
        api_base_url = _strip_trailing_slash(payload.get("apiBaseUrl", ""))
        return api_base_url or LOCAL_BACKEND_URL
    except Exception:
        return LOCAL_BACKEND_URL


def build_device_id() -> str:
    return _strip_trailing_slash(os.getenv("MASTER_DEVICE_ID", "")) or socket.gethostname().lower() or "desktop-master"


def build_server_binding_payload(api_token: str, device_id: str) -> Dict[str, str]:
    hostname = socket.gethostname() or "localhost"
    try:
        server_ip = socket.gethostbyname(hostname)
    except Exception:
        server_ip = "127.0.0.1"
    return {
        "api_token": api_token,
        "device_id": device_id,
        "server_domain": hostname,
        "server_ip": server_ip,
        "hardware_hash": f"{hostname}-{device_id}",
    }


def login_master(server: str, *, email: str, password: str, device_id: str) -> Dict[str, Any]:
    response = requests.post(
        f"{server}/admin/login",
        json={
            "email": email,
            "password": password,
            "device_id": device_id,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def ensure_server_binding(server: str, *, api_token: str, device_id: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_token}",
        "X-Device-Id": device_id,
    }
    response = requests.post(
        f"{server}/admin/register-server",
        headers=headers,
        json=build_server_binding_payload(api_token, device_id),
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    return str((payload.get("admin") or {}).get("server_id") or "")


def protected_headers(*, api_token: str, device_id: str, server_id: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "X-Device-Id": device_id,
        "X-Server-Id": server_id,
    }


def fetch_json(url: str, *, headers: Dict[str, str] | None = None) -> Dict[str, Any]:
    response = requests.get(url, headers=headers or {}, timeout=10)
    response.raise_for_status()
    return response.json()


def main() -> None:
    master_email = os.getenv("MASTER_EMAIL", "").strip()
    master_password = os.getenv("MASTER_PASSWORD", "").strip()
    if not master_email or not master_password:
        raise SystemExit("Set MASTER_EMAIL and MASTER_PASSWORD before running this script.")

    server = resolve_backend_url()
    device_id = build_device_id()

    print(f"Resolved backend: {server}")
    login_data = login_master(server, email=master_email, password=master_password, device_id=device_id)
    api_token = str(login_data.get("api_token") or "").strip()
    if not api_token:
        raise SystemExit("Login succeeded but api_token was missing from the response.")

    server_id = str((login_data.get("admin") or {}).get("server_id") or "").strip()
    if not server_id:
        server_id = ensure_server_binding(server, api_token=api_token, device_id=device_id)
    if not server_id:
        raise SystemExit("Could not resolve or register a server_id for the master account.")

    headers = protected_headers(api_token=api_token, device_id=device_id, server_id=server_id)

    version_info = fetch_json(f"{server}/api/version?tenant_id=master&client=mobile", headers=headers)
    streams_info = fetch_json(f"{server}/analytics/streams", headers=headers)
    live_scores = fetch_json(f"{server}/football-data/live-scores", headers=headers)
    standings = fetch_json(f"{server}/football-data/standings/PL", headers=headers)
    fixtures = fetch_json(f"{server}/football-data/fixtures/PL", headers=headers)

    output = {
        "server": server,
        "device_id": device_id,
        "server_id": server_id,
        "version": version_info,
        "streams": streams_info,
        "live_scores": live_scores,
        "standings": standings,
        "fixtures": fixtures,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
