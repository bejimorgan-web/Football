from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.routes import tenant
from app import storage


class TenantAuthResolutionTests(unittest.TestCase):
    def test_admin_token_tenant_mismatch_is_rejected(self) -> None:
        with patch.object(tenant, "validate_tenant_access_token", side_effect=ValueError("not a tenant token")), \
            patch.object(
                tenant,
                "validate_admin_api_token",
                return_value={"tenant_id": "master", "role": "master"},
            ):
            with self.assertRaises(HTTPException) as context:
                tenant._resolve_requested_tenant("Bearer token-123", "johne-c47921")

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail, "Token tenant does not match requested tenant.")

    def test_tenant_login_uses_requested_tenant_credentials(self) -> None:
        resolved_tenant = {
            "tenant_id": "johne-c47921",
            "admin_credentials": {"username": "owner", "password": "secret"},
        }

        with patch.object(tenant, "authenticate_tenant_admin", return_value=resolved_tenant) as mocked_auth, \
            patch.object(tenant, "create_tenant_access_token", return_value={"token": "abc", "expires_at": "later"}), \
            patch.object(tenant, "get_branding_config", return_value={"tenant_id": "johne-c47921"}):
            result = tenant.tenant_login(tenant.TenantLoginPayload(tenant_id="johne-c47921", username="owner", password="secret"))

        mocked_auth.assert_called_once_with("johne-c47921", "owner", "secret")
        self.assertEqual(result["tenant"]["tenant_id"], "johne-c47921")

    def test_authenticate_tenant_admin_falls_back_to_linked_admin_email_credentials(self) -> None:
        tenant_record = {
            "tenant_id": "clubtv",
            "admin_credentials": {"username": "", "password": ""},
        }
        admin_record = {
            "admin_id": "admin-1",
            "tenant_id": "clubtv",
            "email": "owner@example.com",
            "password_salt": "salt-1",
            "password_hash": storage._hash_secret("secret123", "salt-1"),
        }

        with patch.object(storage, "get_tenant", return_value=tenant_record), \
            patch.object(storage, "get_admin_by_tenant_id", return_value=admin_record):
            result = storage.authenticate_tenant_admin("clubtv", "owner@example.com", "secret123")

        self.assertEqual(result["tenant_id"], "clubtv")


if __name__ == "__main__":
    unittest.main()
