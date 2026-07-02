"""
core.py

Shared Facebook video/reel download logic used by both the CLI
(fb_downloader.py) and the web app (app.py). Uses the yt-dlp Python API
directly — no subprocess.

Only intended for public videos or videos the user owns.
"""

import os
import re
import subprocess
import unicodedata

import yt_dlp

MAX_CAPTION_LEN = 70
INVALID_CHARS_PATTERN = re.compile(r'[\\/:*?"<>|\n\r\t]')
URL_PATTERN = re.compile(r'https?://\S+')

_SUPPORTED_DOMAINS = (
    "facebook.com", "fb.watch",
    "tiktok.com", "vm.tiktok.com",
)

import shutil as _shutil

# If ffmpeg is available, download the absolute best quality (any codec) and let
# yt-dlp re-encode/remux to H.264 mp4 so QuickTime can open it.
# Without ffmpeg we fall back to the best native H.264 stream available.
_FFMPEG  = _shutil.which("ffmpeg")
_FFPROBE = _shutil.which("ffprobe")


def _label_for_height(h: int) -> str:
    if h >= 2160:
        return f"4K ({h}p)"
    if h >= 1440:
        return f"2K ({h}p)"
    return f"{h}p"


def format_for_height(height=None) -> str:
    """Return yt-dlp format string for the given max height (None = best available).
    Always prefer native H.264 streams to avoid costly re-encoding on cloud servers."""
    cap = f"[height<={height}]" if height else ""
    return (
        f"bestvideo{cap}[vcodec^=avc1]+bestaudio[acodec^=mp4a]"
        f"/bestvideo{cap}[vcodec^=avc1]+bestaudio"
        f"/bestvideo{cap}[vcodec^=avc]+bestaudio"
        f"/bestvideo{cap}[vcodec^=h264]+bestaudio"
        f"/bestvideo{cap}+bestaudio[acodec^=mp4a]"
        f"/bestvideo{cap}+bestaudio"
        f"/best{cap}/best"
    )


PREFERRED_FORMAT = format_for_height(None)


def _postprocessors():
    """Remux to mp4 container (stream-copy only; H.264 re-encoding done separately)."""
    if not _FFMPEG:
        return []
    return [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]


def ensure_h264_mp4(src: str, out: str) -> bool:
    """
    Guarantee the output file is H.264 video + AAC audio inside an mp4 container,
    which is required for QuickTime/macOS compatibility.

    - If the source video is already H.264: stream-copy (fast, lossless).
    - Otherwise (VP9, AV1, HEVC …): re-encode to H.264 CRF-18 (high quality).
    Returns True on success.
    """
    if not _FFMPEG:
        return False

    try:
        probe_bin = _FFPROBE or (_FFMPEG.replace("ffmpeg", "ffprobe") if _FFMPEG else None)
        r = subprocess.run(
            [probe_bin, "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=nw=1:nk=1", src],
            capture_output=True, text=True, timeout=30,
        )
        vcodec = r.stdout.strip().lower()
    except Exception:
        vcodec = ""

    is_h264 = vcodec in ("h264", "avc", "avc1")

    if is_h264:
        cmd = [_FFMPEG, "-i", src, "-c", "copy", "-movflags", "+faststart", "-y", out]
    else:
        cmd = [
            _FFMPEG, "-i", src,
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", "-y", out,
        ]

    result = subprocess.run(cmd, capture_output=True, timeout=7200)
    return result.returncode == 0


def strip_emoji(text: str) -> str:
    if not text:
        return text
    emoji_pattern = re.compile(
        "["
        "\U0001F1E0-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0001F000-\U0001F0FF"
        "\U00002190-\U000021FF"
        "\U00002300-\U000023FF"
        "\U0000FE00-\U0000FE0F"
        "\U0001F900-\U0001F9FF"
        "\U00002B00-\U00002BFF"
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "So")
    return text


def sanitize_filename(caption: str, fallback_id: str) -> str:
    caption = (caption or "").strip()
    if caption:
        caption = URL_PATTERN.sub("", caption)          # strip http(s):// links
        caption = strip_emoji(caption)
        caption = INVALID_CHARS_PATTERN.sub(" ", caption)
        caption = re.sub(r"\s+", " ", caption).strip()
        caption = caption[:MAX_CAPTION_LEN].strip()
        caption = caption.rstrip(". ")
    if not caption:
        caption = f"facebook_video_{fallback_id}"
    return caption


def unique_path(directory: str, base_name: str, ext: str) -> str:
    candidate = os.path.join(directory, f"{base_name}.{ext}")
    if not os.path.exists(candidate):
        return candidate
    counter = 1
    while True:
        candidate = os.path.join(directory, f"{base_name}_{counter}.{ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def detect_platform(url: str) -> str:
    u = url.lower()
    if "facebook.com" in u or "fb.watch" in u:
        return "facebook"
    if "tiktok.com" in u:
        return "tiktok"
    return "other"


def validate_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return False
    lower = url.lower()
    return any(d in lower for d in _SUPPORTED_DOMAINS)


def friendly_error_message(err: Exception) -> str:
    msg = str(err)
    lower = msg.lower()

    if any(k in lower for k in ("login", "log in", "private", "not available", "permission")):
        return f"Không thể tải video — video này có thể là riêng tư hoặc cần đăng nhập.\n{msg}"

    if any(k in lower for k in ("unsupported url", "is not a valid url", "invalid url")):
        return f"URL không hợp lệ hoặc không được hỗ trợ.\n{msg}"

    if "unable to extract" in lower or "no video formats" in lower:
        return (
            f"Không thể lấy dữ liệu video — có thể do yt-dlp đã cũ.\n{msg}\n"
            "Gợi ý: chạy 'pip install -U yt-dlp' để cập nhật."
        )

    return f"Lỗi khi tải video:\n{msg}"


class DownloadFailure(RuntimeError):
    def __init__(self, message: str, caption: str = ""):
        super().__init__(message)
        self.caption = caption


def _make_progress_hook(on_event):
    def hook(d):
        if on_event is None:
            return
        if d.get("status") == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            percent = (downloaded / total * 100) if total else None
            on_event({
                "type": "progress",
                "percent": percent,
                "speed": d.get("speed"),
                "eta": d.get("eta"),
            })
        elif d.get("status") == "finished":
            on_event({"type": "progress", "percent": 100, "speed": None, "eta": 0})
    return hook


def probe_one(url: str) -> dict:
    """Fetch metadata only — no download.
    Returns {caption, video_id, filename, ext}.
    Raises ValueError for bad URL, DownloadFailure otherwise.
    """
    if not validate_url(url):
        raise ValueError(
            f"URL không được hỗ trợ: {url!r}\n"
            "Hỗ trợ: Facebook, TikTok."
        )

    probe_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 30,
        "extractor_retries": 1,
        "extractor_args": {"youtube": {"player_client": ["ios", "android"]}},
    }

    try:
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadFailure(friendly_error_message(e)) from e
    except Exception as e:
        raise DownloadFailure(friendly_error_message(e)) from e

    if info is None:
        raise DownloadFailure("Không lấy được metadata của video (kết quả rỗng).")

    video_id = info.get("id") or "unknown"
    caption = info.get("description") or info.get("title") or ""
    base_name = sanitize_filename(caption, video_id)
    ext = info.get("ext") or "mp4"

    # Collect unique resolutions. Accept any format that has a valid height and
    # is not audio-only (vcodec == "none"). Some FB Reels return combined streams
    # where vcodec may be empty/None even though it's a real video format.
    heights: dict = {}
    for f in (info.get("formats") or []):
        h = f.get("height")
        if not h or not isinstance(h, int) or h <= 0:
            continue
        vcodec = (f.get("vcodec") or "none").lower()
        if vcodec == "none":          # strictly audio-only → skip
            continue
        tbr = f.get("tbr") or f.get("vbr") or 0
        if h not in heights or tbr > heights[h]:
            heights[h] = tbr

    # Fallback 1: top-level height on the info dict (the selected/best format).
    if not heights:
        h = info.get("height")
        if h and isinstance(h, int) and h > 0:
            heights[h] = 0

    # Fallback 2: any format with a height, ignoring codec entirely.
    if not heights:
        for f in (info.get("formats") or []):
            h = f.get("height")
            if h and isinstance(h, int) and h > 0:
                heights[h] = f.get("tbr") or 0

    # Fallback 3: requested_formats (what yt-dlp actually selected).
    if not heights:
        for rf in (info.get("requested_formats") or []):
            h = rf.get("height")
            if h and isinstance(h, int) and h > 0:
                heights[h] = rf.get("tbr") or 0
                break

    resolutions = [
        {"height": h, "label": _label_for_height(h)}
        for h in sorted(heights.keys(), reverse=True)
    ]

    return {
        "caption": caption,
        "video_id": video_id,
        "filename": f"{base_name}.{ext}",
        "ext": ext,
        "resolutions": resolutions,
        "platform": detect_platform(url),
    }


def download_one(url: str, output_dir: str, on_event=None) -> dict:
    """Download a single Facebook video.

    on_event(event) callbacks:
      {"type": "probing"}
      {"type": "caption", "caption": str, "video_id": str, "filename": str}
      {"type": "progress", "percent": float|None, "speed": float|None, "eta": int|None}

    Returns {"path": str, "caption": str, "video_id": str}.
    Raises ValueError for bad URL, DownloadFailure for everything else.
    """
    if not validate_url(url):
        raise ValueError(f"URL không hợp lệ: {url!r} (cần là link facebook.com hoặc fb.watch)")

    os.makedirs(output_dir, exist_ok=True)

    if on_event:
        on_event({"type": "probing"})

    probe_opts = {"quiet": True, "no_warnings": True, "skip_download": True}

    try:
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadFailure(friendly_error_message(e)) from e
    except Exception as e:
        raise DownloadFailure(friendly_error_message(e)) from e

    if info is None:
        raise DownloadFailure("Không lấy được metadata của video (kết quả rỗng).")

    video_id = info.get("id") or "unknown"
    caption = info.get("description") or info.get("title") or ""
    base_name = sanitize_filename(caption, video_id)

    ext = info.get("ext") or "mp4"
    target_path = unique_path(output_dir, base_name, ext)
    final_base = os.path.splitext(os.path.basename(target_path))[0]
    output_template = os.path.join(output_dir, f"{final_base}.%(ext)s")

    if on_event:
        on_event({
            "type": "caption",
            "caption": caption,
            "video_id": video_id,
            "filename": f"{final_base}.{ext}",
        })

    dl_opts = {
        "format": PREFERRED_FORMAT,
        "outtmpl": output_template,
        "progress_hooks": [_make_progress_hook(on_event)],
        "postprocessors": _postprocessors(),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "merge_output_format": "mp4",
    }

    try:
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        raise DownloadFailure(friendly_error_message(e), caption=caption) from e
    except Exception as e:
        raise DownloadFailure(friendly_error_message(e), caption=caption) from e

    saved_path = target_path
    if not os.path.exists(saved_path):
        saved_path = None
        for fname in os.listdir(output_dir):
            if fname.startswith(final_base + "."):
                saved_path = os.path.join(output_dir, fname)
                break

    if saved_path is None:
        raise DownloadFailure("Tải xong nhưng không tìm thấy file đã lưu.", caption=caption)

    return {"path": saved_path, "caption": caption, "video_id": video_id}
