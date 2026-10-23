import os
import re
import time
import uuid
import threading
import logging
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, request, jsonify, render_template, send_file, abort
from flask_cors import CORS
import yt_dlp
import requests

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("VideoDownloader")

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory download task tracker
# { download_id: { status, percent, speed, eta, filename, filepath, error, timestamp } }
download_tasks = {}
tasks_lock = threading.Lock()

# Auto cleanup old files (older than 30 mins)
def cleanup_old_files():
    while True:
        try:
            now = time.time()
            cutoff = now - (30 * 60)  # 30 minutes
            with tasks_lock:
                expired_ids = []
                for task_id, task in list(download_tasks.items()):
                    if task.get("timestamp", 0) < cutoff:
                        filepath = task.get("filepath")
                        if filepath and os.path.exists(filepath):
                            try:
                                os.remove(filepath)
                                logger.info(f"Cleaned up expired file: {filepath}")
                            except Exception as e:
                                logger.error(f"Error removing {filepath}: {e}")
                        expired_ids.append(task_id)
                for tid in expired_ids:
                    download_tasks.pop(tid, None)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        time.sleep(300)  # Check every 5 minutes

cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()


def sanitize_filename(filename: str) -> str:
    # Remove invalid characters for Windows and Unix filesystems
    cleaned = re.sub(r'[\\/*?:"<>|]', "", filename)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "video"


def format_duration(seconds):
    if not seconds:
        return "Unknown"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_filesize(bytes_val):
    if not bytes_val or bytes_val <= 0:
        return "Unknown size"
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} TB"


def get_base_ydl_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "retries": 3,
        "socket_timeout": 15,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
        opts["ffmpeg_location"] = FFMPEG_PATH
    return opts


@app.route("/")
def index():
    # Support both nested templates/ folder and flat root directory
    tmpl_nested = os.path.join(BASE_DIR, "templates", "index.html")
    tmpl_root = os.path.join(BASE_DIR, "index.html")
    
    target_file = tmpl_nested if os.path.exists(tmpl_nested) else tmpl_root
    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()
            # If static assets were uploaded to root, fix the asset paths
            if not os.path.exists(os.path.join(BASE_DIR, "static", "css", "style.css")):
                content = content.replace("/static/css/style.css", "/style.css")
                content = content.replace("/static/js/app.js", "/app.js")
            return content
    return "ClipStream server is online."


@app.route("/style.css")
def serve_root_css():
    path = os.path.join(BASE_DIR, "style.css")
    if os.path.exists(path):
        return send_file(path, mimetype="text/css")
    abort(404)


@app.route("/app.js")
def serve_root_js():
    path = os.path.join(BASE_DIR, "app.js")
    if os.path.exists(path):
        return send_file(path, mimetype="application/javascript")
    abort(404)


@app.route("/api/extract", methods=["POST"])
def extract_info():
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "Please provide a valid video URL."}), 400

    parsed = urlparse(url)
    if not (parsed.scheme in ("http", "https") and parsed.netloc):
        return jsonify({"error": "Invalid URL format. Must start with http:// or https://"}), 400

    ydl_opts = get_base_ydl_opts()
    ydl_opts["skip_download"] = True

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({"error": "Failed to extract video information."}), 400

            title = info.get("title") or "Untitled Video"
            duration = info.get("duration")
            thumbnail = info.get("thumbnail") or ""
            uploader = info.get("uploader") or info.get("channel") or info.get("creator") or "Unknown Creator"
            extractor = info.get("extractor_key") or info.get("extractor") or "Direct/Web"
            views = info.get("view_count")

            # Parse available video resolutions and formats
            raw_formats = info.get("formats", [])
            video_options = []
            audio_options = []
            seen_resolutions = set()

            # Inspect formats
            for f in raw_formats:
                height = f.get("height")
                ext = f.get("ext", "mp4")
                vcodec = f.get("vcodec", "none")
                acodec = f.get("acodec", "none")
                filesize = f.get("filesize") or f.get("filesize_approx")

                # Video format (must have video stream)
                if vcodec != "none" and height and height >= 144:
                    res_key = f"{height}p"
                    if res_key not in seen_resolutions:
                        seen_resolutions.add(res_key)
                        video_options.append({
                            "resolution": f"{height}p",
                            "height": height,
                            "ext": "mp4",
                            "format_id": f.get("format_id"),
                            "filesize_str": format_filesize(filesize) if filesize else "Estimated",
                            "label": f"{height}p Full HD" if height >= 1080 else f"{height}p HD" if height >= 720 else f"{height}p SD"
                        })

                # Audio format (audio only)
                if vcodec == "none" and acodec != "none":
                    abr = f.get("abr")
                    audio_options.append({
                        "ext": "mp3",
                        "format_id": f.get("format_id"),
                        "bitrate": f"{int(abr)} kbps" if abr else "128 kbps",
                        "filesize_str": format_filesize(filesize) if filesize else "High Quality"
                    })

            # Sort video options by height descending
            video_options.sort(key=lambda x: x["height"], reverse=True)

            # If no parsed video options (e.g. direct mp4 or single stream format), add standard default
            if not video_options:
                video_options.append({
                    "resolution": "best",
                    "height": 1080,
                    "ext": "mp4",
                    "format_id": "best",
                    "filesize_str": "Original Quality",
                    "label": "Best Available Quality"
                })

            # Standardized audio option
            standard_audio = [
                {
                    "type": "mp3",
                    "label": "MP3 Audio (High Quality 192kbps)",
                    "ext": "mp3",
                    "bitrate": "192 kbps"
                },
                {
                    "type": "m4a",
                    "label": "M4A Audio (Lossless/Original)",
                    "ext": "m4a",
                    "bitrate": "Original"
                }
            ]

            return jsonify({
                "success": True,
                "url": url,
                "title": title,
                "thumbnail": thumbnail,
                "duration": format_duration(duration),
                "duration_raw": duration,
                "uploader": uploader,
                "platform": extractor,
                "views": f"{views:,}" if views else None,
                "video_options": video_options[:6],  # Top 6 video qualities
                "audio_options": standard_audio,
                "has_ffmpeg": bool(FFMPEG_PATH and os.path.exists(FFMPEG_PATH))
            })

    except yt_dlp.utils.DownloadError as de:
        err_msg = str(de)
        if "Private video" in err_msg or "Sign in" in err_msg:
            return jsonify({"error": "This video is private, age-restricted, or requires login credentials."}), 400
        elif "HTTP Error 404" in err_msg:
            return jsonify({"error": "Video not found. Please verify the URL."}), 400
        elif "HTTP Error 403" in err_msg:
            return jsonify({"error": "Access forbidden by host. The video might be geo-restricted or protected."}), 400
        else:
            return jsonify({"error": f"Failed to extract video: {err_msg.split(';')[-1].strip()}"}), 400
    except Exception as e:
        logger.exception("Extraction failed")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500


def background_downloader(task_id, url, download_type, resolution, target_ext):
    try:
        def progress_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                if total > 0:
                    percent = round((downloaded / total) * 100, 1)
                else:
                    raw_str = d.get("_percent_str", "0%").replace("%", "").strip()
                    try:
                        percent = float(raw_str)
                    except ValueError:
                        percent = 0.0

                speed = d.get("_speed_str", "").strip()
                eta = d.get("_eta_str", "").strip()

                with tasks_lock:
                    if task_id in download_tasks:
                        download_tasks[task_id].update({
                            "status": "downloading",
                            "percent": percent,
                            "speed": speed or "Calculating...",
                            "eta": eta or "Calculating..."
                        })
            elif d["status"] == "finished":
                with tasks_lock:
                    if task_id in download_tasks:
                        download_tasks[task_id].update({
                            "status": "converting",
                            "percent": 98.0,
                            "speed": "Merging streams & finalizing...",
                            "eta": "A few seconds"
                        })

        ydl_opts = get_base_ydl_opts()
        outtmpl_pattern = os.path.join(DOWNLOAD_DIR, f"{task_id}_%(title).120s.%(ext)s")
        ydl_opts["outtmpl"] = outtmpl_pattern
        ydl_opts["progress_hooks"] = [progress_hook]

        if download_type == "audio":
            if target_ext == "mp3":
                ydl_opts["format"] = "bestaudio/best"
                if FFMPEG_PATH:
                    ydl_opts["postprocessors"] = [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }]
            else:
                ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
        else:
            # Video type
            if resolution and resolution != "best":
                # Select best video up to requested resolution + best audio
                height = re.sub(r"[^0-9]", "", resolution)
                if height and FFMPEG_PATH:
                    ydl_opts["format"] = (
                        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
                        f"bestvideo[height<={height}]+bestaudio/"
                        f"best[height<={height}][ext=mp4]/best[height<={height}]/best"
                    )
                    ydl_opts["merge_output_format"] = "mp4"
                elif height:
                    ydl_opts["format"] = f"best[height<={height}]/best"
                else:
                    ydl_opts["format"] = "bestvideo+bestaudio/best"
            else:
                if FFMPEG_PATH:
                    ydl_opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
                    ydl_opts["merge_output_format"] = "mp4"
                else:
                    ydl_opts["format"] = "best"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title") or "download"

        # Locate the downloaded file for this task
        found_file = None
        for fname in os.listdir(DOWNLOAD_DIR):
            if fname.startswith(f"{task_id}_") and not fname.endswith(".part") and not fname.endswith(".ytdl"):
                found_file = os.path.join(DOWNLOAD_DIR, fname)
                break

        if not found_file or not os.path.exists(found_file):
            raise Exception("Processed file could not be located on server.")

        filesize = os.path.getsize(found_file)
        clean_name = sanitize_filename(title)
        _, ext = os.path.splitext(found_file)
        display_filename = f"{clean_name}{ext}"

        with tasks_lock:
            if task_id in download_tasks:
                download_tasks[task_id].update({
                    "status": "completed",
                    "percent": 100.0,
                    "filepath": found_file,
                    "filename": display_filename,
                    "filesize": filesize,
                    "filesize_str": format_filesize(filesize),
                    "speed": "Done",
                    "eta": "Ready"
                })

    except Exception as e:
        logger.exception(f"Download task {task_id} failed")
        with tasks_lock:
            if task_id in download_tasks:
                download_tasks[task_id].update({
                    "status": "error",
                    "error": str(e)
                })


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    download_type = data.get("type", "video")  # 'video' or 'audio'
    resolution = data.get("resolution", "best")
    target_ext = data.get("ext", "mp4" if download_type == "video" else "mp3")

    if not url:
        return jsonify({"error": "Missing video URL"}), 400

    task_id = str(uuid.uuid4())[:8]

    with tasks_lock:
        download_tasks[task_id] = {
            "status": "queued",
            "percent": 0.0,
            "speed": "Starting...",
            "eta": "Calculating...",
            "filename": "",
            "filepath": "",
            "error": None,
            "timestamp": time.time()
        }

    thread = threading.Thread(
        target=background_downloader,
        args=(task_id, url, download_type, resolution, target_ext),
        daemon=True
    )
    thread.start()

    return jsonify({
        "success": True,
        "task_id": task_id
    })


@app.route("/api/progress/<task_id>")
def get_progress(task_id):
    with tasks_lock:
        task = download_tasks.get(task_id)
        if not task:
            return jsonify({"status": "not_found", "error": "Task not found"}), 404
        return jsonify(task)


@app.route("/api/file/<task_id>")
def get_downloaded_file(task_id):
    with tasks_lock:
        task = download_tasks.get(task_id)

    if not task:
        abort(404, "Download task expired or not found.")

    if task.get("status") != "completed":
        abort(400, "File is not ready yet.")

    filepath = task.get("filepath")
    filename = task.get("filename") or "download.mp4"

    if not filepath or not os.path.exists(filepath):
        abort(404, "File was removed or not found.")

    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n========================================================")
    print(f"  ClipStream Video Downloader is launching!")
    print(f"  Access the website at: http://127.0.0.1:{port}")
    print(f"  FFmpeg acceleration: {'Enabled (' + FFMPEG_PATH + ')' if FFMPEG_PATH else 'Disabled'}")
    print(f"========================================================\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
