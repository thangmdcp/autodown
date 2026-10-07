import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app
import gallery_photos as photos


class GalleryTests(unittest.TestCase):
    def test_order_caption_and_dedup(self):
        rows = [[2, {"post_text": "caption https://s.shopee.vn/test", "title": "album"}]]
        rows += [[3, "https://cdn.fbcdn.net/1", {"id": "1"}], [3, "https://cdn.fbcdn.net/1", {"id": "1"}], [3, "https://cdn.fbcdn.net/2", {"id": "2"}]]
        caption, assets = photos.select_photos(rows)
        self.assertTrue(caption.startswith("caption"))
        self.assertEqual([item["id"] for item in assets], ["1", "2"])

    def test_empty_video_and_limit(self):
        for rows, code in [([], "GALLERY_EMPTY_MEDIA"), ([[3, "url", {"type": "video"}]], "GALLERY_VIDEO_SOURCE"),
                           ([[3, "url", {"id": str(i)}] for i in range(51)], "GALLERY_TOO_MANY_PHOTOS")]:
            with self.assertRaises(photos.PhotoError) as caught:
                photos.select_photos(rows)
            self.assertEqual(caught.exception.code, code)

    def test_routing(self):
        self.assertTrue(app._photo_candidate("https://www.facebook.com/user/posts/pfbid123"))
        self.assertTrue(app._photo_candidate("https://www.facebook.com/permalink.php?story_fbid=123"))
        self.assertFalse(app._photo_candidate("https://www.facebook.com/reel/123"))
        self.assertFalse(app._photo_candidate("https://evilfacebook.com/user/posts/123"))
        self.assertFalse(app._photo_candidate("https://www.facebook.com/user"))

    def test_photo_api_and_no_ytdlp(self):
        app._DOWNLOAD_CACHE.clear()
        payload = {"success": True, "extractor": "gallery-dl", "caption": "caption", "media": [{"type": "photo", "url": "https://cdn/1", "public_id": "postflow-fetch/1"}]}
        client = app.app.test_client()
        with patch.object(app.cloudinary_client, "is_configured", return_value=True), patch.object(app, "_download_photos", return_value=payload) as download, patch.object(app, "_run_yt_dlp_download") as video:
            response = client.post("/api/download", json={"url": "https://www.facebook.com/user/posts/test"}, headers={"X-API-Key": app.API_KEY})
        self.assertEqual(response.status_code, 200)
        download.assert_called_once()
        video.assert_not_called()
        self.assertEqual(response.get_json()["extractor"], "gallery-dl")

    def test_login_is_nonretryable_and_does_not_try_video(self):
        app._DOWNLOAD_CACHE.clear()
        with patch.object(app.cloudinary_client, "is_configured", return_value=True), patch.object(app, "_download_photos", return_value={"success": False, "code": "LOGIN_REQUIRED", "retryable": False, "http_status": 422}), patch.object(app, "_run_yt_dlp_download") as video:
            response = app.app.test_client().post("/api/download", json={"url": "https://www.facebook.com/user/posts/test"}, headers={"X-API-Key": app.API_KEY})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.get_json()["retryable"])
        video.assert_not_called()

    def test_photo_concurrency_busy_without_wait(self):
        with patch.object(app._PHOTO_SEM, "acquire", return_value=False), patch.object(app.subprocess, "run") as run:
            result = app._download_photos("url", {})
        self.assertEqual(result["code"], "GALLERY_BUSY")
        run.assert_not_called()

    def test_deadline_structured(self):
        import subprocess
        with patch.object(app.subprocess, "run", side_effect=subprocess.TimeoutExpired("gallery", 60)):
            result = app._download_photos("url", {})
        self.assertEqual(result["code"], "UPSTREAM_TIMEOUT")
        self.assertEqual(app._ACTIVE_PHOTOS, 0)

if __name__ == "__main__":
    unittest.main()
