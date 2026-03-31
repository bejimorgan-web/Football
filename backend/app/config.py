import os

DEFAULT_API_URL = (
    os.getenv("DEFAULT_API_URL")
    or os.getenv("API_BASE_URL")
    or os.getenv("PUBLIC_SERVER_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or ""
).strip()
