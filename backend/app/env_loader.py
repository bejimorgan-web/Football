from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def load_backend_env(*, worker: bool = False) -> None:
    load_dotenv(BACKEND_ROOT / ".env", override=False)

    if worker:
        load_dotenv(BACKEND_ROOT / ".env.worker", override=True)  # ✅ FIX