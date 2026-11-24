"""Анализ исходного файла: разрешение, поворот, FPS, HDR, звук."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path

from .utils import ffprobe, parse_rate

# Стандартные частоты кадров — к ним приводим VFR-видео с iPhone/Android
STANDARD_FPS = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001),
                Fraction(30), Fraction(50), Fraction(60000, 1001), Fraction(60)]
MAX_FPS = Fraction(60)  # Instagram не принимает больше 60 к/с


@dataclass
class MediaInfo:
    path: str
    width: int            # ширина с учётом поворота (как видит зритель)
    height: int
    rotation: int
    fps: Fraction         # итоговая частота кадров для монтажа
    src_fps: float
    duration: float
    vcodec: str
    pix_fmt: str
    bit_depth: int
    color_transfer: str
    color_primaries: str
    hdr: bool
    video_bitrate: int
    has_audio: bool
    acodec: str
    sample_rate: int
    channels: int

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fps"] = f"{self.fps.numerator}/{self.fps.denominator}"
        return d


def _rotation(stream: dict) -> int:
    rot = 0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    tags = stream.get("tags", {}) or {}
    if not rot and "rotate" in tags:
        try:
            rot = int(tags["rotate"])
        except ValueError:
            pass
    return rot % 360


def _pick_fps(stream: dict) -> tuple[Fraction, float]:
    avg = parse_rate(stream.get("avg_frame_rate"))
    real = parse_rate(stream.get("r_frame_rate"))
    raw = avg if avg > 0 else real
    if raw <= 0:
        raw = Fraction(30)
    raw = min(raw, Fraction(240))
    target = min(raw, MAX_FPS)
    best = min(STANDARD_FPS, key=lambda f: abs(float(f) - float(target)))
    return best, float(raw)


def probe(path: Path) -> MediaInfo:
    data = ffprobe(path)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition", {}) or {}).get("attached_pic")), None)
    if v is None:
        raise ValueError("в файле нет видеодорожки")
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)

    w, h = int(v["width"]), int(v["height"])
    rot = _rotation(v)
    if rot in (90, 270):
        w, h = h, w

    fps, src_fps = _pick_fps(v)
    dur = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    pix = v.get("pix_fmt", "")
    depth = int(v.get("bits_per_raw_sample") or (10 if "10" in pix else 8))
    trc = v.get("color_transfer", "") or ""
    hdr = trc in ("smpte2084", "arib-std-b67")
    vbr = int(v.get("bit_rate") or data.get("format", {}).get("bit_rate") or 0)

    return MediaInfo(
        path=str(path), width=w, height=h, rotation=rot, fps=fps, src_fps=src_fps,
        duration=dur, vcodec=v.get("codec_name", ""), pix_fmt=pix, bit_depth=depth,
        color_transfer=trc, color_primaries=v.get("color_primaries", "") or "",
        hdr=hdr, video_bitrate=vbr, has_audio=a is not None,
        acodec=(a or {}).get("codec_name", ""),
        sample_rate=int((a or {}).get("sample_rate") or 0),
        channels=int((a or {}).get("channels") or 0),
    )
