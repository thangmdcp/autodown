"""
cloudinary_client.py — thin wrapper around the Cloudinary SDK.

No local persistence here — credentials are passed in by the caller
(app.py) on every call, since this app is stateless.
"""

import cloudinary
import cloudinary.api
import cloudinary.uploader


def is_configured(cfg: dict) -> bool:
    return bool((cfg or {}).get("cloud_name") and (cfg or {}).get("api_key") and (cfg or {}).get("api_secret"))


def configure(cfg: dict):
    cloudinary.config(
        cloud_name=cfg.get("cloud_name", ""),
        api_key=cfg.get("api_key", ""),
        api_secret=cfg.get("api_secret", ""),
        secure=True,
    )


def upload_file(path: str, folder: str, resource_type: str = "video") -> dict:
    result = cloudinary.uploader.upload(path, folder=folder, resource_type=resource_type)
    return {
        "secure_url": result["secure_url"],
        "public_id": result["public_id"],
        "resource_type": result.get("resource_type", resource_type),
    }


def delete_assets(public_ids: list) -> dict:
    """Try each resource type since Cloudinary deletes are scoped by type
    and /api/cleanup only receives public_ids without their type."""
    deleted: dict = {}
    for rtype in ("video", "image", "raw"):
        try:
            resp = cloudinary.api.delete_resources(public_ids, resource_type=rtype)
        except Exception:
            continue
        for pid, status in (resp.get("deleted") or {}).items():
            if status == "deleted" or pid not in deleted:
                deleted[pid] = status
    return deleted
