"""Minimal production API. No local UI, cookie configuration or key disclosure."""
import hashlib
import contextlib
import hmac
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import shutil
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8192
_slot = threading.BoundedSemaphore(1)
MAX_BYTES = 100 * 1024 * 1024


def valid_source(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        return parsed.scheme == 'https' and not parsed.username and not parsed.password and parsed.port in (None, 443) and any(host == d or host.endswith('.' + d) for d in ('facebook.com', 'fb.watch', 'tiktok.com'))
    except ValueError:
        return False


@app.before_request
def authenticate():
    if request.path == '/healthz' and request.method == 'GET':
        return None
    key = os.environ.get('API_KEY', '')
    if not key or not hmac.compare_digest(request.headers.get('X-API-Key', ''), key):
        return jsonify(success=False, code='UNAUTHORIZED'), 401
    if request.path != '/api/download':
        return jsonify(success=False, code='NOT_FOUND'), 404


@app.get('/healthz')
def health():
    return jsonify(ok=True)


@app.post('/api/download')
def download():
    data = request.get_json(silent=True) or {}
    url, request_id = data.get('url'), data.get('requestId')
    if not isinstance(url, str) or not valid_source(url) or not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', request_id):
        return jsonify(success=False, code='INVALID_REQUEST'), 400
    if not _slot.acquire(blocking=False):
        response = jsonify(success=False, code='MEDIA_BUSY')
        response.headers['Retry-After'] = '10'
        return response, 503
    directory = tempfile.mkdtemp(prefix='render-download-')
    process = None
    try:
        process = subprocess.Popen([sys.executable, __file__, '--child', directory], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        output, _ = process.communicate(json.dumps({'url': url, 'requestId': request_id}), timeout=270)
        result = json.loads(output)
        return jsonify(result), (200 if result.get('success') else result.get('httpStatus', 502))
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return jsonify(success=False, code='UPSTREAM_TIMEOUT'), 504
    except Exception:
        app.logger.warning('Render child did not return a valid structured result')
        return jsonify(success=False, code='DOWNLOAD_FAILED'), 502
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        _slot.release()


def run_child(data, directory):
    import cloudinary
    import cloudinary.api
    import cloudinary.uploader
    import core
    import yt_dlp
    cloudinary.config(cloud_name=os.environ['CLOUDINARY_CLOUD_NAME'], api_key=os.environ['CLOUDINARY_API_KEY'], api_secret=os.environ['CLOUDINARY_API_SECRET'], secure=True)
    public_id = 'postflow-fetch/video-' + data['requestId']
    source_hash = hashlib.sha256(data['url'].encode()).hexdigest()
    try:
        existing = cloudinary.api.resource(public_id, resource_type='video', context=True, timeout=20)
    except cloudinary.exceptions.NotFound:
        existing = None
    if existing:
        context = existing.get('context', {}).get('custom', {})
        if context.get('source_sha256') != source_hash:
            return {'success': False, 'code': 'ASSET_CONFLICT', 'httpStatus': 409}
        # Caption is cached before upload; if a restart removed it, metadata-only
        # probing recovers the caption without downloading the video again.
        caption = core.probe_one(data['url']).get('caption', '')
        return result(existing, caption)
    def bound(progress):
        if progress.get('downloaded_bytes', 0) > MAX_BYTES or (progress.get('total_bytes') or 0) > MAX_BYTES:
            raise ValueError('MEDIA_TOO_LARGE')
    opts = {'format': core.format_for_height(), 'outtmpl': str(Path(directory) / '%(id)s.%(ext)s'), 'quiet': True, 'no_warnings': True, 'noplaylist': True, 'max_filesize': MAX_BYTES, 'socket_timeout': 20, 'retries': 1, 'fragment_retries': 1, 'progress_hooks': [bound], 'concurrent_fragment_downloads': 2}
    opts.update(core.network_options_for_url(data['url']))
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(data['url'], download=True)
    if not info or info.get('_type') in ('playlist', 'multi_video'):
        return {'success': False, 'code': 'INVALID_MEDIA', 'httpStatus': 422}
    if (info.get('filesize') or info.get('filesize_approx') or 0) > MAX_BYTES:
        return {'success': False, 'code': 'MEDIA_TOO_LARGE', 'httpStatus': 413}
    files = [p for p in Path(directory).iterdir() if p.is_file() and not p.name.endswith(('.part', '.ytdl'))]
    if not files:
        return {'success': False, 'code': 'MEDIA_UNAVAILABLE', 'httpStatus': 502}
    path = max(files, key=lambda p: p.stat().st_size)
    if path.stat().st_size > MAX_BYTES:
        return {'success': False, 'code': 'MEDIA_TOO_LARGE', 'httpStatus': 413}
    asset = cloudinary.uploader.upload(str(path), resource_type='video', public_id=public_id, overwrite=False, timeout=80, context={'source_sha256': source_hash})
    return result(asset, info.get('description') or info.get('title') or '')


def result(asset, caption):
    return {'success': True, 'caption': caption, 'type': 'video', 'extractor': 'render-yt-dlp', 'media': [{'type': 'video', 'url': asset['secure_url'], 'public_id': asset['public_id']}]}


if __name__ == '__main__' and '--child' in sys.argv:
    try:
        # Extractors occasionally print warnings even in quiet mode. Keep the
        # stdout pipe exclusively JSON so a successful upload isn't lost.
        with contextlib.redirect_stdout(sys.stderr):
            payload = run_child(json.loads(sys.stdin.read()), sys.argv[-1])
    except Exception as error:
        import cloudinary.exceptions
        text = str(error).lower()
        storage = isinstance(error, (cloudinary.exceptions.Error, KeyError))
        code = 'MEDIA_TOO_LARGE' if 'media_too_large' in text else 'CLOUDINARY_FAILED' if storage else 'DOWNLOAD_FAILED'
        payload = {'success': False, 'code': code, 'httpStatus': 413 if code == 'MEDIA_TOO_LARGE' else 502}
    print(json.dumps(payload))
