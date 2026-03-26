from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TenantModel(BaseModel):
    tenant_id: str
    name: str
    mobile_app_generated: bool = False
    mobile_app_package_id: Optional[str] = None
    mobile_app_created_at: Optional[datetime] = None
