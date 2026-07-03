#!/usr/bin/env python3
"""
app.py — FB Downloader web app (Flask, localhost only).
Two-phase flow: probe (caption only) → per-item download → stream to browser.
"""

import concurrent.futures
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
import uuid
import webbrowser

import yt_dlp
from flask import Flask, abort, after_this_request, jsonify, render_template, request, send_file

import cloudinary_client
import core

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Persistent API config ──────────────────────────────────────────────────
_CONFIG_FILE = os.path.join(BASE_DIR, ".api_config.json")

def _load_config() -> dict:
    # On cloud (Render/Railway): use API_KEY env var so key survives redeploys
    env_key = os.environ.get("API_KEY", "").strip()
    if env_key:
        return {"api_key": env_key, "key_name": "production"}
    # Local: persist to file
    if os.path.exists(_CONFIG_FILE):
        try:
            cfg = json.loads(open(_CONFIG_FILE).read())
            if cfg.get("api_key"):
                return cfg
        except Exception:
            pass
    # Migrate from old plain-text key file
    old = os.path.join(BASE_DIR, ".api_key")
    if os.path.exists(old):
        key = open(old).read().strip()
        if key:
            cfg = {"api_key": key, "key_name": "default"}
            _save_config(cfg)
            return cfg
    cfg = {"api_key": "fbdl-" + secrets.token_hex(16), "key_name": "default"}
    _save_config(cfg)
    return cfg

def _save_config(cfg: dict):
    with open(_CONFIG_FILE, "w") as f:
        json.dump(cfg, f)

_config = _load_config()
API_KEY: str = _config["api_key"]


# ── Cloudinary config (env var priority, same pattern as API_KEY) ──────────
def _cloudinary_env() -> dict | None:
    cloud  = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
    key    = os.environ.get("CLOUDINARY_API_KEY", "").strip()
    secret = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
    if cloud and key and secret:
        return {"cloud_name": cloud, "api_key": key, "api_secret": secret}
    return None


def _cloudinary_config() -> dict:
    return _cloudinary_env() or (_config.get("cloudinary") or {})


app = Flask(__name__)

# ── CORS (allow other local apps to call the API) ──────────────────────────
# Only allows localhost/127.0.0.1 origins for security.
_ALLOWED_ORIGINS = {
    "http://localhost", "http://127.0.0.1",
    "https://autodown.vibevic.com",
}

@app.after_request
def _add_cors(response):
    origin = request.headers.get("Origin", "")
    # strip port from origin for comparison
    base = origin.rsplit(":", 1)[0] if ":" in origin[7:] else origin
    if base in _ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

@app.route("/api/<path:_>", methods=["OPTIONS"])
def _cors_preflight(_):
    resp = jsonify({})
    resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
    return resp, 204

# ── API key check (external callers must send correct key) ─────────────────
@app.before_request
def _check_api_key():
    if not request.path.startswith("/api/"):
        return
    if request.method == "OPTIONS":
        return
    # /api/info is public (returns key to the local UI)
    if request.path == "/api/info":
        return
    provided = (
        request.headers.get("X-API-Key") or
        request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )
    if provided != API_KEY:
        return jsonify({"error": "Thiếu hoặc sai API key. Gửi header X-API-Key: <key>."}), 401

@app.route("/api/info")
def api_info():
    port = request.host.split(":")[-1] if ":" in request.host else "5000"
    base = f"http://127.0.0.1:{port}"
    return jsonify({
        "api_key":  API_KEY,
        "key_name": _config.get("key_name", "default"),
        "base_url": base,
        "auth":     "X-API-Key: <api_key>",
    })


@app.route("/api/regenerate_key", methods=["POST"])
def regenerate_key():
    global API_KEY, _config
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "default").strip()[:60]
    _config["api_key"]  = "fbdl-" + secrets.token_hex(16)
    _config["key_name"] = name
    API_KEY = _config["api_key"]
    _save_config(_config)
    return jsonify({"api_key": API_KEY, "key_name": name})


@app.route("/api/cloudinary_config", methods=["GET", "POST"])
def cloudinary_config_route():
    env = _cloudinary_env()

    if request.method == "GET":
        cfg = env or (_config.get("cloudinary") or {})
        return jsonify({
            "cloud_name":     cfg.get("cloud_name", ""),
            "api_key":        cfg.get("api_key", ""),
            "api_secret_set": bool(cfg.get("api_secret")),
            "source":         "env" if env else "config",
        })

    if env:
        return jsonify({
            "error": "Cloudinary đang được cấu hình qua biến môi trường server, không thể sửa qua giao diện."
        }), 409

    data       = request.get_json(force=True) or {}
    cloud_name = (data.get("cloud_name") or "").strip()
    api_key    = (data.get("api_key") or "").strip()
    api_secret = (data.get("api_secret") or "").strip()

    existing = _config.get("cloudinary") or {}
    if not api_secret:
        api_secret = existing.get("api_secret", "")

    if not (cloud_name and api_key and api_secret):
        return jsonify({"error": "Vui lòng nhập đủ Cloud Name, API Key và API Secret."}), 400

    _config["cloudinary"] = {"cloud_name": cloud_name, "api_key": api_key, "api_secret": api_secret}
    _save_config(_config)
    return jsonify({"success": True})


# probe_id -> {items: list[dict], finished: bool, created: float}
PROBES: dict = {}

# dl_id -> {status, percent, speed, eta, path, filename, tmpdir, error, created}
DOWNLOADS: dict = {}
# 1 concurrent yt-dlp download — client processes links serially so this is the natural limit
_DL_SEM = threading.Semaphore(1)


# ── Probe phase ────────────────────────────────────────────────────────────────

def _new_probe_item(url: str) -> dict:
    return {
        "url": url,
        "status": "queued",
        "caption": "",
        "video_id": "",
        "filename": "",
        "ext": "mp4",
        "error": "",
        "platform": core.detect_platform(url),
    }


_PROBE_TIMEOUT = 75  # seconds per URL


def _probe_one_item(item: dict):
    item["status"] = "probing"
    try:
        result = core.probe_one(item["url"])
        item.update({"status": "done", **result})
    except ValueError as e:
        item["status"] = "error"
        item["error"] = str(e)
    except core.DownloadFailure as e:
        item["status"] = "error"
        item["error"] = str(e).splitlines()[0]
    except Exception as e:
        item["status"] = "error"
        item["error"] = f"Lỗi: {str(e)[:200]}"


def _probe_worker(probe_id: str):
    probe = PROBES[probe_id]
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_item = {
            executor.submit(_probe_one_item, item): item
            for item in probe["items"]
        }
        done, not_done = concurrent.futures.wait(
            future_to_item.keys(), timeout=_PROBE_TIMEOUT
        )
        for future in not_done:
            item = future_to_item[future]
            item["status"] = "error"
            item["error"] = "Quá thời gian chờ. Video có thể cần đăng nhập hoặc bị chặn."
            future.cancel()
    probe["finished"] = True


def _asset_version(rel_path: str) -> int:
    full = os.path.join(BASE_DIR, "static", rel_path)
    try:
        return int(os.path.getmtime(full))
    except OSError:
        return 0


@app.route("/")
def index():
    return render_template(
        "index.html",
        js_v=_asset_version("js/app.js"),
        css_v=_asset_version("css/style.css"),
    )


@app.route("/api/probe", methods=["POST"])
def probe():
    urls_raw = request.form.get("urls", "")
    urls = [u.strip() for u in urls_raw.splitlines()
            if u.strip() and not u.strip().startswith("#")]
    if not urls:
        return jsonify({"error": "Vui lòng nhập ít nhất 1 link."}), 400

    probe_id = uuid.uuid4().hex[:12]
    PROBES[probe_id] = {
        "items": [_new_probe_item(u) for u in urls],
        "finished": False,
        "created": time.time(),
    }
    threading.Thread(target=_probe_worker, args=(probe_id,), daemon=True).start()
    return jsonify({"probe_id": probe_id})


@app.route("/api/probe_status/<probe_id>")
def probe_status(probe_id: str):
    probe = PROBES.get(probe_id)
    if not probe:
        return jsonify({"error": "Không tìm thấy."}), 404
    return jsonify({"finished": probe["finished"], "items": probe["items"]})


# ── Download phase ─────────────────────────────────────────────────────────────

def _dl_progress_hook(dl: dict):
    def hook(d):
        if d.get("status") == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dl["percent"] = (downloaded / total * 100) if total else None
            dl["speed"] = d.get("speed")
            dl["eta"] = d.get("eta")
        elif d.get("status") == "finished":
            dl["percent"] = 100
    return hook


def _run_yt_dlp_download(url: str, height=None, progress_hook=None) -> dict:
    """Runs yt-dlp against url and returns {path, filename, caption, video_id, tmpdir}.
    Raises on failure. Caller is responsible for cleaning up the returned tmpdir."""
    tmpdir = tempfile.mkdtemp(prefix="fbdl_")
    outtmpl = os.path.join(tmpdir, "%(id)s.%(ext)s")
    opts = {
        "format": core.format_for_height(height),
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "concurrent_fragment_downloads": 4,
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
    }
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Get filepath from yt-dlp info (most reliable)
    src = None
    if info:
        for rdl in (info.get("requested_downloads") or []):
            fp = rdl.get("filepath") or rdl.get("filename")
            if fp and os.path.exists(fp):
                src = fp
                break

    # Fallback: largest file in tmpdir
    if not src:
        candidates = sorted(
            [f for f in os.listdir(tmpdir) if not f.endswith(".part")],
            key=lambda f: os.path.getsize(os.path.join(tmpdir, f)),
            reverse=True,
        )
        if not candidates:
            raise RuntimeError("Tải xong nhưng không tìm thấy file.")
        src = os.path.join(tmpdir, candidates[0])

    if not os.path.exists(src):
        raise RuntimeError(f"File không tồn tại: {os.path.basename(src)}")

    caption = ""
    video_id = ""
    if info:
        caption  = info.get("description") or info.get("title") or ""
        video_id = info.get("id") or ""

    return {
        "path":     src,
        "filename": core.sanitize_filename(caption, video_id) + ".mp4",
        "caption":  caption,
        "video_id": video_id,
        "tmpdir":   tmpdir,
    }


def _download_worker(dl_id: str, url: str, height=None):
    dl = DOWNLOADS[dl_id]
    # "queued" while waiting for a semaphore slot
    dl["status"] = "queued"

    _DL_SEM.acquire()
    try:
        dl["status"] = "downloading"
        result = _run_yt_dlp_download(url, height, progress_hook=_dl_progress_hook(dl))
        dl["tmpdir"]   = result["tmpdir"]
        dl["path"]     = result["path"]
        dl["filename"] = result["filename"]
        dl["caption"]  = result["caption"]
        dl["status"]   = "done"
        dl["percent"]  = 100
    except Exception as e:
        dl["status"] = "error"
        dl["error"]  = str(e).splitlines()[0]
        if dl.get("tmpdir"):
            shutil.rmtree(dl["tmpdir"], ignore_errors=True)
        dl["tmpdir"] = None
    finally:
        _DL_SEM.release()


@app.route("/api/start_dl", methods=["POST"])
def start_dl():
    data   = request.get_json(force=True) or {}
    url    = (data.get("url") or "").strip()
    height = data.get("height")

    if not url:
        return jsonify({"error": "Thiếu URL."}), 400
    if not core.validate_url(url):
        return jsonify({"error": "URL không hợp lệ."}), 400
    if height is not None:
        try:
            height = int(height)
        except (ValueError, TypeError):
            height = None

    dl_id = uuid.uuid4().hex[:12]
    DOWNLOADS[dl_id] = {
        "status": "queued", "percent": 0, "speed": None, "eta": None,
        "path": None, "filename": None, "caption": None,
        "tmpdir": None, "error": None, "created": time.time(),
    }
    threading.Thread(
        target=_download_worker,
        args=(dl_id, url, height),
        daemon=True,
    ).start()
    return jsonify({"dl_id": dl_id})


@app.route("/api/dl_status/<dl_id>")
def dl_status(dl_id: str):
    dl = DOWNLOADS.get(dl_id)
    if not dl:
        return jsonify({"error": "Không tìm thấy."}), 404
    return jsonify({k: v for k, v in dl.items() if k not in ("path", "tmpdir")})


@app.route("/api/dl_file/<dl_id>")
def dl_file(dl_id: str):
    dl = DOWNLOADS.get(dl_id)
    if not dl:
        return jsonify({"error": "Download không tồn tại (server restart?). Tải lại trang và thử lại."}), 404
    if dl["status"] != "done":
        return jsonify({"error": f"Trạng thái không hợp lệ: {dl['status']}"}), 404
    path = dl.get("path")
    if not path:
        return jsonify({"error": "Đường dẫn file trống."}), 404
    if not os.path.exists(path):
        return jsonify({"error": f"File bị mất trên server: {os.path.basename(path)}"}), 404

    tmpdir = dl.get("tmpdir")

    @after_this_request
    def _cleanup(response):
        def _rm():
            time.sleep(30)
            DOWNLOADS.pop(dl_id, None)
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
        threading.Thread(target=_rm, daemon=True).start()
        return response

    return send_file(
        path,
        as_attachment=True,
        download_name=dl["filename"],
        mimetype="video/mp4",
    )


# ── Stateless internal API: extract → download+upload → cleanup ────────────
# Used by another web app as a backend integration. No job storage — every
# call is self-contained; the caller holds onto the returned public_ids and
# is responsible for calling /api/cleanup once it no longer needs the asset.

@app.route("/api/extract", methods=["POST"])
def api_extract():
    data = request.get_json(force=True) or {}
    url  = (data.get("url") or "").strip()

    if not url:
        return jsonify({"success": False, "error": "Thiếu URL."}), 400
    if not core.validate_url(url):
        return jsonify({"success": False, "error": "URL không hợp lệ hoặc không được hỗ trợ. Chỉ hỗ trợ Facebook, TikTok, YouTube."}), 400

    try:
        result = core.probe_one(url)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except core.DownloadFailure as e:
        return jsonify({"success": False, "error": str(e).splitlines()[0]}), 502
    except Exception as e:
        return jsonify({"success": False, "error": f"Lỗi: {str(e)[:200]}"}), 500

    return jsonify({
        "success":    True,
        "platform":   result["platform"],
        "type":       "video",
        "caption":    result["caption"],
        "thumbnail":  result.get("thumbnail"),
        "mediaCount": 1,
    })


@app.route("/api/download", methods=["POST"])
def api_download():
    data   = request.get_json(force=True) or {}
    url    = (data.get("url") or "").strip()
    height = data.get("height")

    if not url:
        return jsonify({"success": False, "error": "Thiếu URL."}), 400
    if not core.validate_url(url):
        return jsonify({"success": False, "error": "URL không hợp lệ hoặc không được hỗ trợ. Chỉ hỗ trợ Facebook, TikTok, YouTube."}), 400
    if height is not None:
        try:
            height = int(height)
        except (ValueError, TypeError):
            height = None

    cloud_cfg = _cloudinary_config()
    if not cloudinary_client.is_configured(cloud_cfg):
        return jsonify({
            "success": False,
            "error": "Chưa cấu hình Cloudinary. Vào mục \"Cloudinary Configuration\" trên giao diện để nhập Cloud Name / API Key / API Secret.",
        }), 400

    _DL_SEM.acquire()
    try:
        result = _run_yt_dlp_download(url, height)
    except Exception as e:
        return jsonify({"success": False, "error": str(e).splitlines()[0]}), 502
    finally:
        _DL_SEM.release()

    tmpdir = result["tmpdir"]
    try:
        cloudinary_client.configure(cloud_cfg)
        folder = f"temp/{uuid.uuid4().hex[:10]}"
        upload = cloudinary_client.upload_file(result["path"], folder=folder, resource_type="video")
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"success": False, "error": f"Lỗi upload Cloudinary: {str(e)[:200]}"}), 502

    shutil.rmtree(tmpdir, ignore_errors=True)

    return jsonify({
        "success": True,
        "caption": result["caption"],
        "type":    "video",
        "media": [{
            "type":      "video",
            "url":       upload["secure_url"],
            "public_id": upload["public_id"],
        }],
    })


@app.route("/api/cleanup", methods=["POST"])
def api_cleanup():
    data       = request.get_json(force=True) or {}
    public_ids = data.get("public_ids")

    if not isinstance(public_ids, list) or not public_ids:
        return jsonify({"success": False, "error": "public_ids là bắt buộc và phải là danh sách không rỗng."}), 400

    cloud_cfg = _cloudinary_config()
    if not cloudinary_client.is_configured(cloud_cfg):
        return jsonify({"success": False, "error": "Chưa cấu hình Cloudinary."}), 400

    cloudinary_client.configure(cloud_cfg)
    deleted = cloudinary_client.delete_assets(public_ids)
    return jsonify({"success": True, "deleted": deleted})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if not os.environ.get("PORT"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
