"""Cookie-free, bounded Facebook photo extraction; runs in an isolated process."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

import requests
from PIL import Image
import cloudinary
import cloudinary.api
import cloudinary.uploader

VERSION = "1.32.15"
MAX_PHOTOS = 50
MAX_BYTES = 25 * 1024 * 1024


class PhotoError(Exception):
    def __init__(self, code, retryable=False, status=422):
        self.code, self.retryable, self.status = code, retryable, status


def select_photos(rows):
    photos, seen, caption = [], set(), ""
    for row in rows:
        if row[0] == 2 and not caption:
            caption = row[1].get("post_text") or row[1].get("caption") or ""
        if row[0] != 3:
            continue
        meta = row[2]
        if meta.get("type") in ("video", "audio") or meta.get("extension", "").lower() in ("mp4", "m4a", "webm"):
            raise PhotoError("GALLERY_VIDEO_SOURCE")
        identity = str(meta.get("id") or row[1])
        if identity in seen:
            continue
        seen.add(identity)
        photos.append({"id": identity, "url": row[1]})
        caption = caption or meta.get("post_text") or meta.get("caption") or ""
        if len(photos) > MAX_PHOTOS:
            raise PhotoError("GALLERY_TOO_MANY_PHOTOS")
    if not photos:
        raise PhotoError("GALLERY_EMPTY_MEDIA")
    return caption, photos


def run(url, cfg):
    started = time.monotonic()
    result = subprocess.run([
        sys.executable, "-m", "gallery_dl", "--ignore-config", "--dump-json",
        "--no-download", "--retries", "0", "-o", "extractor.timeout=15",
        "-o", "extractor.facebook.author-followups=false",
        "-o", "extractor.facebook.loop=false", "-o", "extractor.facebook.fallback-retries=0", url,
    ], capture_output=True, text=True, timeout=45)
    if result.returncode:
        error = result.stderr.lower()
        if "logged in" in error or "cookies" in error or "authentication" in error:
            raise PhotoError("LOGIN_REQUIRED")
        if "unsupported" in error:
            raise PhotoError("GALLERY_UNSUPPORTED")
        raise PhotoError("GALLERY_PARSE_FAILED", True, 502)
    if "[error]" in result.stderr.lower() or "skipping" in result.stderr.lower():
        raise PhotoError("GALLERY_INCOMPLETE_MEDIA", True, 502)
    caption, photos = select_photos(json.loads(result.stdout))
    cloudinary.config(**cfg, secure=True)
    media = []
    with tempfile.TemporaryDirectory(prefix="gallery-photos-") as directory:
        for i, photo in enumerate(photos):
            if time.monotonic() - started >= 55:
                raise PhotoError("UPSTREAM_TIMEOUT", True, 504)
            # Stable IDs let interrupted uploads resume without creating duplicate assets.
            pid = "postflow-fetch/" + hashlib.sha256((url + "|" + photo["id"]).encode()).hexdigest()
            try:
                asset = cloudinary.api.resource(pid, resource_type="image", timeout=10)
            except cloudinary.exceptions.NotFound:
                asset = None
            if not asset:
                parsed = urlparse(photo["url"])
                if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".fbcdn.net"):
                    raise PhotoError("GALLERY_INVALID_MEDIA")
                path = os.path.join(directory, str(i))
                with requests.get(photo["url"], stream=True, timeout=(5, 15), allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise PhotoError("DOWNLOAD_FAILED", True, 502)
                    size = 0
                    with open(path, "wb") as output:
                        for chunk in response.iter_content(65536):
                            size += len(chunk)
                            if size > MAX_BYTES or time.monotonic() - started >= 55:
                                raise PhotoError("DOWNLOAD_FAILED", True, 502)
                            output.write(chunk)
                with Image.open(path) as image:
                    if image.format not in ("JPEG", "PNG", "WEBP", "GIF"):
                        raise PhotoError("GALLERY_INVALID_MEDIA")
                    image.verify()
                asset = cloudinary.uploader.upload(path, public_id=pid, resource_type="image", overwrite=False, timeout=15)
            media.append({"type": "photo", "url": asset["secure_url"], "public_id": asset["public_id"], "source_id": photo["id"]})
    return {"success": True, "extractor": "gallery-dl", "extractorVersion": VERSION,
            "caption": caption, "type": "photo", "media": media}


if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
        payload = run(data["url"], data["cloudinary"])
    except PhotoError as error:
        payload = {"success": False, "code": error.code, "retryable": error.retryable, "http_status": error.status}
    except subprocess.TimeoutExpired:
        payload = {"success": False, "code": "UPSTREAM_TIMEOUT", "retryable": True, "http_status": 504}
    except Exception:
        payload = {"success": False, "code": "GALLERY_DOWNLOAD_FAILED", "retryable": True, "http_status": 502}
    print(json.dumps(payload))
