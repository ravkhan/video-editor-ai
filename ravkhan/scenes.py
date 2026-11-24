"""Анализ сцен (PySceneDetect) и умное вертикальное кадрирование 9:16
по лицам (детектор YuNet из OpenCV)."""
from __future__ import annotations

import re
import statistics
import subprocess
from pathlib import Path

import numpy as np

from .utils import ROOT, log, run, warn

YUNET = ROOT / "models" / "face_detection_yunet_2023mar.onnx"
SAMPLE_FPS = 2          # сколько кадров в секунду анализировать на лица
ANALYSIS_W = 640        # ширина кадра для анализа


def detect_scenes(src: Path, info, threshold: float) -> tuple[list[tuple[float, float]], str]:
    try:
        from scenedetect import AdaptiveDetector, detect
        raw = detect(str(src), AdaptiveDetector(adaptive_threshold=threshold),
                     start_in_scene=True)
        scenes = [(s.seconds if hasattr(s, "seconds") else s.get_seconds(),
                   e.seconds if hasattr(e, "seconds") else e.get_seconds()) for s, e in raw]
        method = "PySceneDetect"
    except Exception as exc:  # noqa: BLE001
        warn(f"PySceneDetect не сработал ({exc}); использую FFmpeg scene filter")
        proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-map", "0:v:0",
                    "-vf", "scale=320:-2,select='gt(scene,0.35)',showinfo", "-f", "null", "-"])
        cuts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", proc.stderr)]
        bounds = [0.0] + cuts + [info.duration]
        scenes = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)
                  if bounds[i + 1] > bounds[i]]
        method = "ffmpeg-scene"
    if not scenes:
        scenes = [(0.0, info.duration)]
    # последняя сцена — до конца файла
    scenes[-1] = (scenes[-1][0], max(scenes[-1][1], info.duration))
    log(f"Сцены ({method}): найдено {len(scenes)}")
    return scenes, method


def _face_samples(src: Path, info) -> list[tuple[float, float | None]]:
    """Возвращает [(время, центр лица по X в долях ширины или None)]."""
    if not YUNET.exists():
        warn("Модель лиц не найдена — кадрирование по центру (запустите ./setup.sh)")
        return []
    import cv2

    aw = ANALYSIS_W if info.width >= ANALYSIS_W else info.width - info.width % 2
    ah = int(round(info.height * aw / info.width / 2)) * 2
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (aw, ah), 0.75, 0.3, 50)
    cmd = ["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:v:0",
           "-vf", f"fps={SAMPLE_FPS},scale={aw}:{ah}", "-f", "rawvideo",
           "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = aw * ah * 3
    out, i = [], 0
    assert p.stdout
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(ah, aw, 3)
        _, faces = det.detect(frame)
        t = i / SAMPLE_FPS
        if faces is not None and len(faces):
            # самое крупное лицо (обычно — говорящий)
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])[:4]
            out.append((t, float((x + w / 2) / aw)))
        else:
            out.append((t, None))
        i += 1
    p.wait()
    return out


def crop_centers(src: Path, info, scenes: list[tuple[float, float]], mode: str) -> list[float]:
    """Центр кадрирования (доля ширины) для каждой сцены."""
    if mode != "face":
        return [0.5] * len(scenes)
    samples = _face_samples(src, info)
    centers, prev = [], 0.5
    found = 0
    for s, e in scenes:
        xs = [x for t, x in samples if s <= t < e and x is not None]
        total = sum(1 for t, _ in samples if s <= t < e)
        if xs and len(xs) >= max(1, 0.3 * total):
            c = statistics.median(xs)
            found += 1
        else:
            c = prev if centers else 0.5
        centers.append(c)
        prev = c
    log(f"Кадрирование: лица найдены в {found} из {len(scenes)} сцен")
    return centers


def scene_thumbnails(src: Path, scenes: list[tuple[float, float]], out_dir: Path,
                     limit: int = 60) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    step = max(1, len(scenes) // limit + (1 if len(scenes) % limit else 0))
    for idx in range(0, len(scenes), step):
        s, e = scenes[idx]
        t = s + (e - s) / 2
        p = out_dir / f"scene_{idx + 1:03d}_{t:07.2f}s.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src),
             "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "3", str(p)], check=False)
        if p.exists():
            paths.append(p)
    return paths
