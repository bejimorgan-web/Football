from __future__ import annotations

import unittest
from unittest.mock import patch

from app.routes import mobile_builder


class MobileBuilderRouteTests(unittest.TestCase):
    def test_create_mobile_build_uses_authenticated_user(self) -> None:
        current_user = {"admin_id": "admin-123", "role": "client"}
        expected = {"build_id": "build-1", "status": "queued"}

        with patch.object(mobile_builder, "_queue_build_for_current_user", return_value=expected) as mocked:
            result = mobile_builder.create_mobile_build(current_user)

        mocked.assert_called_once_with(current_user)
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
