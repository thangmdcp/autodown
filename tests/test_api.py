import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app
import core


class AutoDownApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.headers = {"X-API-Key": app.API_KEY, "Content-Type": "application/json"}

    def test_facebook_parse_error_is_structured_and_permanent(self):
        error = core.classify_download_error(Exception("ERROR: [facebook] 123: Cannot parse data"))
        self.assertEqual(error["code"], "FACEBOOK_PARSE_FAILED")
        self.assertEqual(error["http_status"], 422)
        self.assertFalse(error["retryable"])

    def test_health_is_authenticated_and_reports_readiness(self):
        denied = self.client.get("/api/health")
        self.assertEqual(denied.status_code, 401)
        with patch.object(app.cloudinary_client, "is_configured", return_value=True):
            response = self.client.get("/api/health", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["cloudinaryReady"])
        self.assertIn("ytDlpVersion", payload)

    def test_download_fetches_and_uploads_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "video.mp4")
            with open(path, "wb") as handle:
                handle.write(b"video")
            result = {"path": path, "tmpdir": directory, "caption": "caption", "video_id": "123"}
            with patch.object(app, "_cloudinary_config", return_value={"cloud_name": "x", "api_key": "y", "api_secret": "z"}), \
                 patch.object(app.cloudinary_client, "is_configured", return_value=True), \
                 patch.object(app, "_run_yt_dlp_download", return_value=result) as download, \
                 patch.object(app.cloudinary_client, "configure"), \
                 patch.object(app.cloudinary_client, "upload_file", return_value={"secure_url": "https://example.com/video.mp4", "public_id": "temp/test/video"}) as upload:
                response = self.client.post("/api/download", headers=self.headers, json={"url": "https://www.facebook.com/reel/123"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["success"])
            download.assert_called_once()
            upload.assert_called_once()


if __name__ == "__main__":
    unittest.main()
