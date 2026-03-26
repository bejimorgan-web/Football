import os

DEFAULT_API_URL = (
    os.getenv("DEFAULT_API_URL")
    or os.getenv("API_BASE_URL")
    or os.getenv("PUBLIC_SERVER_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or "http://127.0.0.1:8000"
).strip() or "http://127.0.0.1:8000"
