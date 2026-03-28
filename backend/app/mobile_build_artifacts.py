from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict

import boto3

BACKEND_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ARTIFACTS_ROOT = BACKEND_ROOT / "generated_apps"


def artifact_storage_backend() -> str:
    return str(os.environ.get("MOBILE_BUILD_ARTIFACT_STORAGE", "local") or "local").strip().lower() or "local"


def store_mobile_build_artifact(*, tenant_id: str, artifact_name: str, source_apk: Path) -> Dict[str, str]:
    backend = artifact_storage_backend()
    if backend == "s3":
        return _store_mobile_build_artifact_s3(tenant_id=tenant_id, artifact_name=artifact_name, source_apk=source_apk)
    return _store_mobile_build_artifact_local(tenant_id=tenant_id, artifact_name=artifact_name, source_apk=source_apk)


def resolve_mobile_build_download(job: Dict[str, object]) -> Dict[str, str]:
    backend = str(job.get("artifact_storage") or artifact_storage_backend()).strip().lower() or "local"
    if backend == "s3":
        return _resolve_mobile_build_download_s3(job)
    return _resolve_mobile_build_download_local(job)


def _store_mobile_build_artifact_local(*, tenant_id: str, artifact_name: str, source_apk: Path) -> Dict[str, str]:
    target_dir = LOCAL_ARTIFACTS_ROOT / tenant_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / artifact_name
    shutil.copy2(source_apk, target_path)
    return {
        "artifact_name": artifact_name,
        "artifact_path": str(target_path.resolve()),
        "artifact_storage": "local",
        "artifact_key": str(Path(tenant_id) / artifact_name).replace("\\", "/"),
        "artifact_url": "",
    }


def _store_mobile_build_artifact_s3(*, tenant_id: str, artifact_name: str, source_apk: Path) -> Dict[str, str]:
    bucket = str(os.environ.get("MOBILE_BUILD_S3_BUCKET") or "").strip()
    if not bucket:
        raise RuntimeError("MOBILE_BUILD_S3_BUCKET is required when MOBILE_BUILD_ARTIFACT_STORAGE=s3.")
    prefix = str(os.environ.get("MOBILE_BUILD_S3_PREFIX") or "mobile-builds").strip().strip("/")
    key = "/".join(part for part in (prefix, tenant_id, artifact_name) if part)
    client = _s3_client()
    extra_args = {"ContentType": "application/vnd.android.package-archive"}
    client.upload_file(str(source_apk), bucket, key, ExtraArgs=extra_args)
    public_base_url = str(os.environ.get("MOBILE_BUILD_S3_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    artifact_url = f"{public_base_url}/{key}" if public_base_url else ""
    return {
        "artifact_name": artifact_name,
        "artifact_path": "",
        "artifact_storage": "s3",
        "artifact_key": key,
        "artifact_url": artifact_url,
    }


def _resolve_mobile_build_download_local(job: Dict[str, object]) -> Dict[str, str]:
    artifact_path = Path(str(job.get("artifact_path") or ""))
    if not artifact_path.exists():
        raise ValueError("Generated APK file is missing.")
    return {
        "type": "local",
        "artifact_name": artifact_path.name,
        "artifact_path": str(artifact_path),
        "download_url": "",
    }


def _resolve_mobile_build_download_s3(job: Dict[str, object]) -> Dict[str, str]:
    bucket = str(os.environ.get("MOBILE_BUILD_S3_BUCKET") or "").strip()
    key = str(job.get("artifact_key") or "").strip()
    if not bucket or not key:
        raise ValueError("S3 artifact metadata is incomplete.")
    client = _s3_client()
    expires_in = int(str(os.environ.get("MOBILE_BUILD_S3_PRESIGN_TTL_SECONDS") or "900").strip() or "900")
    download_url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=max(60, expires_in),
    )
    return {
        "type": "redirect",
        "artifact_name": str(job.get("artifact_name") or Path(key).name),
        "artifact_path": "",
        "download_url": download_url,
    }


def _s3_client():
    kwargs = {}
    region = str(os.environ.get("MOBILE_BUILD_S3_REGION") or "").strip()
    endpoint_url = str(os.environ.get("MOBILE_BUILD_S3_ENDPOINT_URL") or "").strip()
    if region:
        kwargs["region_name"] = region
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)
