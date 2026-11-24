"""Поиск пауз (Auto-Editor, запасной вариант — FFmpeg silencedetect)
и построение списка фрагментов, которые остаются в ролике."""
from __future__ import annotations

import json
import math
import re
from fractions import Fraction
from pathlib import Path

from .utils import log, run, tool, warn

TB = 100  # шаг анализа Auto-Editor: 1/100 секунды


def silences_auto_editor(src: Path, work: Path, threshold: float) -> list[tuple[float, float]]:
    out = work / "auto_editor_v1.json"
    run([tool("auto-editor"), str(src),
         "--edit", f"audio:threshold={threshold}",
         "--margin", "0s", "-tb", str(TB),
         "--export", "v1", "-o", str(out),
         "--progress", "none", "--no-open", "--temp-dir", str(work / "ae_tmp")])
    data = json.loads(out.read_text())
    sil = []
    for start, end, speed in data.get("chunks", []):
        if float(speed) != 1.0:
            sil.append((start / TB, end / TB))
    return sil


def silences_ffmpeg(src: Path, noise_db: float, min_len: float) -> list[tuple[float, float]]:
    proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-map", "0:a:0",
                "-af", f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    res = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else math.inf
        res.append((s, e))
    return res


def build_keep_segments(duration: float, silences: list[tuple[float, float]],
                        min_pause: float, pad: float, fps: Fraction,
                        min_segment: float = 0.25) -> list[tuple[float, float]]:
    """Убираем только паузы длиннее min_pause, оставляя по краям pad секунд
    «воздуха», чтобы речь не звучала рублено. Границы выравниваются по кадрам —
    так звук и видео остаются синхронными после любого количества склеек."""
    frame = 1 / float(fps)
    remove = []
    for s, e in silences:
        e = min(e, duration)
        if e - s < min_pause:
            continue
        rs = s + pad if s > 0.01 else 0.0                 # тишина в самом начале
        re_ = e - pad if e < duration - 0.01 else duration  # тишина в самом конце
        if re_ - rs >= frame * 2:
            remove.append((rs, re_))

    keep, cur = [], 0.0
    for rs, re_ in sorted(remove):
        if rs > cur:
            keep.append((cur, rs))
        cur = max(cur, re_)
    if cur < duration:
        keep.append((cur, duration))

    snapped = []
    for s, e in keep:
        fs = round(s / frame)
        fe = math.floor(e / frame + 1e-6)
        if (fe - fs) * frame >= min_segment:
            snapped.append((fs * frame, fe * frame))
    if not snapped:  # всё оказалось тишиной — оставляем видео целиком
        snapped = [(0.0, math.floor(duration / frame) * frame)]
    return snapped


def detect(src: Path, work: Path, info, cfg) -> tuple[list[tuple[float, float]], str]:
    if not info.has_audio or cfg.no_cut:
        reason = "отключено" if cfg.no_cut else "нет звука"
        log(f"Удаление пауз пропущено ({reason})")
        return build_keep_segments(info.duration, [], 1e9, 0, info.fps), "none"
    method = "auto-editor"
    try:
        sil = silences_auto_editor(src, work, cfg.silence_threshold)
    except Exception:
        warn("Auto-Editor не сработал, использую FFmpeg silencedetect")
        method = "ffmpeg-silencedetect"
        sil = silences_ffmpeg(src, cfg.silence_db, cfg.min_pause)
    segs = build_keep_segments(info.duration, sil, cfg.min_pause, cfg.pause_padding, info.fps)
    kept = sum(e - s for s, e in segs)
    log(f"Паузы ({method}): было {info.duration:.1f}s → стало {kept:.1f}s, "
        f"фрагментов: {len(segs)}, вырезано {info.duration - kept:.1f}s")
    return segs, method
