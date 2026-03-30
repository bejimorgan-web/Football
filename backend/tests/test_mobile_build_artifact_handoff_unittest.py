from __future__ import annotations

import base64
import unittest
from pathlib import Path
import shutil
from unittest.mock import patch

from app import mobile_build_artifacts, mobile_builder


class MobileBuildArtifactHandoffTests(unittest.TestCase):
    def test_complete_build_from_worker_stores_uploaded_artifact_locally(self) -> None:
        tmpdir = Path(__file__).resolve().parents[1] / "test-temp" / "artifact-handoff"
        if tmpdir.exists():
            shutil.rmtree(tmpdir, ignore_errors=True)
        artifact_root = tmpdir / "generated_apps"
        payload = {
            "artifact_name": "Goal-TV-1.0.0.apk",
            "artifact_data_base64": base64.b64encode(b"apk-bytes").decode("ascii"),
        }
        job = {
            "build_id": "build-1",
            "tenant_id": "goaltv",
            "package_name": "com.goaltv.mobile",
            "app_name": "Goal TV",
            "logo_file": "",
            "primary_color": "#11B37C",
        }

        try:
            with patch.object(mobile_build_artifacts, "LOCAL_ARTIFACTS_ROOT", artifact_root), \
                patch.object(mobile_builder, "get_build_for_worker", return_value=job), \
                patch.object(mobile_builder, "update_tenant_mobile_app_status"), \
                patch.object(mobile_builder, "save_mobile_app_record"), \
                patch.object(mobile_builder, "_update_job", side_effect=lambda build_id, patch: {"build_id": build_id, **patch}):
                result = mobile_builder.complete_build_from_worker("build-1", payload)

            artifact_path = artifact_root / "goaltv" / "Goal-TV-1.0.0.apk"
            self.assertTrue(artifact_path.exists())
            self.assertEqual(artifact_path.read_bytes(), b"apk-bytes")
            self.assertEqual(result["artifact_storage"], "local")
            self.assertEqual(result["artifact_path"], str(artifact_path.resolve()))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
