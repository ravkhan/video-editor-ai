"""FFmpeg / FFprobe helpers."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Callable

BROWSER_CONTAINERS = {".mp4", ".m4v", ".webm", ".mov"}
BROWSER_VIDEO_CODECS = {"h264", "vp8", "vp9", "av1"}
BROWSER_AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", None}


class MediaError(Exception):
    pass


def probe(path: Path) -> dict:
    """Return duration, display size and codecs of a media file."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise MediaError("Не удалось прочитать файл: это не видео или файл повреждён") from exc
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise MediaError("В файле нет видеодорожки")

    width, height = int(video["width"]), int(video["height"])
    rotation = 0
    for side in video.get("side_data_list", []) or []:
        if "rotation" in side:
            rotation = int(side["rotation"])
    rotation = int(video.get("tags", {}).get("rotate", rotation))
    if abs(rotation) % 180 == 90:
        width, height = height, width

    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
        "has_audio": audio is not None,
    }


def needs_preview(path: Path, info: dict) -> bool:
    """Whether the browser is unlikely to play the source file directly."""
    return (
        path.suffix.lower() not in BROWSER_CONTAINERS
        or info["video_codec"] not in BROWSER_VIDEO_CODECS
        or info["audio_codec"] not in BROWSER_AUDIO_CODECS
    )


def run_ffmpeg(
    args: list[str],
    duration: float,
    on_progress: Callable[[float], None] | None = None,
    cwd: Path | None = None,
) -> None:
    """Run ffmpeg, reporting progress (0..1) parsed from ``-progress pipe:1``."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace"
    )
    stderr_tail: list[str] = []

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line)
            del stderr_tail[:-30]

    reader = threading.Thread(target=drain_stderr, daemon=True)
    reader.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and on_progress and duration > 0 and value.isdigit():
            on_progress(min(int(value) / 1e6 / duration, 1.0))
    proc.wait()
    reader.join(timeout=5)
    if proc.returncode != 0:
        raise MediaError("FFmpeg завершился с ошибкой:\n" + "".join(stderr_tail[-10:]))


def make_preview(source: Path, target: Path, duration: float, on_progress=None) -> None:
    """Transcode to a browser-friendly H.264/AAC MP4 (lower quality, fast)."""
    tmp = target.with_suffix(".tmp.mp4")
    run_ffmpeg(
        [
            "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale='min(1280,iw)':-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(tmp),
        ],
        duration,
        on_progress,
    )
    tmp.replace(target)


def burn_subtitles(project_dir: Path, source: Path, ass_name: str, target: Path, duration: float,
                   on_progress=None) -> None:
    """Render the video with ASS subtitles burned in.

    ffmpeg runs inside the project directory so the subtitle filter gets a
    plain relative file name and needs no path escaping.
    """
    tmp = target.with_suffix(".tmp.mp4")
    run_ffmpeg(
        [
            "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", f"ass={ass_name},scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            tmp.name,
        ],
        duration,
        on_progress,
        cwd=project_dir,
    )
    tmp.replace(target)
