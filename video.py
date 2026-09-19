import os
import re
import subprocess
import urllib.parse
import yt_dlp

from config import MAX_DURATION, TRIM_TO


def detect_platform(url):
    u = url.lower()
    if "tiktok.com"    in u: return "TikTok"
    if "instagram.com" in u: return "Instagram"
    if "youtube.com"   in u or "youtu.be" in u: return "YouTube"
    if "twitter.com"   in u or "x.com"    in u: return "X/Twitter"
    if "facebook.com"  in u: return "Facebook"
    return "Unknown"


def domain_of(url):
    try:
        return urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def trim_video(path, out_dir):
    out = os.path.join(out_dir, "trimmed.mp4")
    try:
        r = subprocess.run([
            "ffmpeg", "-i", path,
            "-t", str(TRIM_TO),
            "-vf", "fps=0.5",
            "-c:v", "libx264",
            "-crf", "28",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-y", out
        ], capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.exists(out):
            orig_mb  = os.path.getsize(path) / 1024 / 1024
            small_mb = os.path.getsize(out)  / 1024 / 1024
            print(f"[Trim] {orig_mb:.1f}MB -> {small_mb:.1f}MB at 0.5fps")
            return out
    except Exception as e:
        print(f"[Trim] ffmpeg failed: {e}")
    return path


def download_video(url, out_dir):
    if re.search(r'tiktok\.com/.+/photo/', url):
        raise ValueError(
            "That's a TikTok photo slideshow, not a video. "
            "DeepCheck only works with video posts."
        )

    opts = {
        "quiet": True, "no_warnings": True,
        "format": "best[height<=360][ext=mp4]/best[height<=360]/worst[ext=mp4]/worst",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(out_dir, "video.%(ext)s"),
        "writeinfojson": False, "writethumbnail": False, "socket_timeout": 15,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except Exception as e:
            msg = str(e)
            if "Unsupported URL" in msg:
                raise ValueError("This URL isn't supported.")
            if "Private video" in msg or "private" in msg.lower():
                raise ValueError("This video is private and can't be accessed.")
            if "removed" in msg.lower() or "deleted" in msg.lower():
                raise ValueError("This video has been removed or deleted.")
            raise ValueError(f"Couldn't download video: {msg[:120]}")

        dur = info.get("duration", 0) or 0
        if dur > MAX_DURATION:
            raise ValueError(
                f"Video is {int(dur)}s — please use clips under {MAX_DURATION//60} minutes."
            )

        fp = ydl.prepare_filename(info)
        if not os.path.exists(fp):
            fp = os.path.join(out_dir, "video.mp4")

        meta = {
            "title":       info.get("title", ""),
            "description": (info.get("description") or "")[:600],
            "uploader":    info.get("uploader") or info.get("channel", ""),
            "duration":    dur,
            "platform":    detect_platform(url),
            "thumbnail":   info.get("thumbnail", ""),
            "view_count":  info.get("view_count"),
            "like_count":  info.get("like_count"),
        }
        return fp, meta