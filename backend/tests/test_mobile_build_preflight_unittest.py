from __future__ import annotations

import unittest
from unittest.mock import patch

from app import mobile_builder


class MobileBuildPreflightTests(unittest.TestCase):
    def test_mobile_build_preflight_reports_ready_for_queue_only_host(self) -> None:
        with patch.object(mobile_builder, "PRIMARY_MOBILE_PROJECT_DIR") as mobile_dir, \
            patch.object(mobile_builder, "ensure_mobile_build_store"), \
            patch.object(mobile_builder, "mobile_build_worker_enabled", return_value=False), \
            patch.object(mobile_builder, "artifact_storage_backend", return_value="local"), \
            patch.dict(mobile_builder.os.environ, {"MOBILE_BUILD_WORKER_TOKEN": "secret"}, clear=False):
            mobile_dir.exists.return_value = True
            result = mobile_builder.mobile_build_preflight()

        self.assertTrue(result["ready"])
        self.assertFalse(result["worker_enabled_on_host"])
        check_map = {item["name"]: item for item in result["checks"]}
        self.assertTrue(check_map["database"]["ok"])
        self.assertTrue(check_map["worker_token"]["ok"])
        self.assertTrue(check_map["docker"]["ok"])


if __name__ == "__main__":
    unittest.main()
