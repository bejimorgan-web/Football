from fastapi import Request

from app.auth import SINGLE_TENANT_ID


async def tenant_resolver(request: Request, call_next):
    request.state.tenant_context = {
        "tenant_id": SINGLE_TENANT_ID,
        "source": "single-tenant",
        "scope": "request",
    }
    response = await call_next(request)
    return response
