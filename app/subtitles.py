"""Subtitle cue building, formatting (SRT / VTT / ASS) and parsing.

A segment (cue) is a dict: {"id": str, "start": float, "end": float, "text": str}.
Text may contain "\n" for an explicit line break.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Iterable

SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")


@dataclass
class Word:
    start: float
    end: float
    text: str  # may contain a leading space, as Whisper produces it


def new_id() -> str:
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------- cue building


def wrap_lines(text: str, max_line: int) -> str:
    """Split text into at most two balanced lines if it is longer than max_line."""
    text = " ".join(text.split())
    if len(text) <= max_line or " " not in text:
        return text
    middle = len(text) / 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    best = min(spaces, key=lambda i: abs(i - middle))
    return text[:best] + "\n" + text[best + 1 :]


def build_cues(
    words: Iterable[Word],
    max_chars: int = 84,
    max_duration: float = 6.0,
    max_gap: float = 0.8,
    max_line: int = 42,
) -> list[dict]:
    """Group word-level timestamps into readable subtitle cues.

    A new cue starts when adding the next word would exceed ``max_chars`` or
    ``max_duration``, or when there is a pause longer than ``max_gap``. A cue
    that ends a sentence is closed unless it is very short (e.g. "Да.").
    """
    cues: list[dict] = []
    current: list[Word] = []

    def flush() -> None:
        if not current:
            return
        text = "".join(w.text for w in current).strip()
        if text:
            cues.append(
                {
                    "id": new_id(),
                    "start": round(current[0].start, 3),
                    "end": round(current[-1].end, 3),
                    "text": wrap_lines(text, max_line),
                }
            )
        current.clear()

    for word in words:
        if not word.text.strip():
            continue
        if current:
            text_len = len("".join(w.text for w in current + [word]).strip())
            gap = word.start - current[-1].end
            duration = word.end - current[0].start
            if text_len > max_chars or duration > max_duration or gap > max_gap:
                flush()
        current.append(word)
        if word.text.strip().endswith(SENTENCE_END):
            if len("".join(w.text for w in current).strip()) >= max(10, max_chars * 0.15):
                flush()
    flush()
    return cues


# ------------------------------------------------------------------ validation


def normalize_segments(raw: Iterable[dict]) -> list[dict]:
    """Validate, clean and sort segments coming from the client or a parser."""
    result = []
    for seg in raw:
        start = max(0.0, float(seg["start"]))
        end = float(seg["end"])
        if end <= start:
            end = start + 0.5
        text = str(seg.get("text", "")).replace("\r\n", "\n").replace("\r", "\n").strip()
        result.append(
            {
                "id": str(seg.get("id") or new_id())[:32],
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            }
        )
    result.sort(key=lambda s: (s["start"], s["end"]))
    return result


# ------------------------------------------------------------------ formatting


def format_timestamp(seconds: float, sep: str = ",") -> str:
    ms_total = int(round(max(0.0, seconds) * 1000))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def to_srt(segments: list[dict]) -> str:
    blocks = []
    for i, seg in enumerate(s for s in segments if s["text"].strip()):
        blocks.append(
            f"{i + 1}\n{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}\n{seg['text'].strip()}\n"
        )
    return "\n".join(blocks)


def to_vtt(segments: list[dict]) -> str:
    blocks = ["WEBVTT\n"]
    for seg in segments:
        if not seg["text"].strip():
            continue
        text = seg["text"].strip().replace("-->", "->")
        blocks.append(
            f"{format_timestamp(seg['start'], '.')} --> {format_timestamp(seg['end'], '.')}\n{text}\n"
        )
    return "\n".join(blocks)


DEFAULT_STYLE = {
    "font": "DejaVu Sans",
    "size": 54,  # px at 1080p, scaled to the real video height
    "bold": True,
    "color": "#FFFFFF",
    "outline_color": "#000000",
    "outline": 3,  # px at 1080p
    "box": False,
    "box_color": "#000000",
    "box_opacity": 0.6,
    "position": "bottom",  # bottom | middle | top
    "margin": 70,  # px at 1080p, distance from the edge
}

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize_style(raw: dict | None, fonts: list[str]) -> dict:
    style = dict(DEFAULT_STYLE)
    for key, value in (raw or {}).items():
        if key not in DEFAULT_STYLE:
            continue
        default = DEFAULT_STYLE[key]
        if isinstance(default, bool):
            style[key] = bool(value)
        elif isinstance(default, (int, float)):
            style[key] = float(value)
        elif key.endswith("color"):
            if isinstance(value, str) and _HEX_COLOR.match(value):
                style[key] = value.upper()
        elif key == "position":
            if value in ("bottom", "middle", "top"):
                style[key] = value
        elif key == "font":
            if value in fonts:
                style[key] = value
    style["size"] = min(max(style["size"], 12), 200)
    style["outline"] = min(max(style["outline"], 0), 20)
    style["margin"] = min(max(style["margin"], 0), 500)
    style["box_opacity"] = min(max(style["box_opacity"], 0.0), 1.0)
    return style


def _ass_color(hex_color: str, opacity: float = 1.0) -> str:
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    alpha = round((1 - opacity) * 255)
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_time(seconds: float) -> str:
    cs_total = int(round(max(0.0, seconds) * 100))
    hours, rem = divmod(cs_total, 360_000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    text = text.strip().replace("\\", "⧵").replace("{", "(").replace("}", ")")
    return text.replace("\n", "\\N")


def to_ass(segments: list[dict], style: dict, width: int, height: int) -> str:
    """Build an ASS script whose coordinate space matches the video exactly."""
    scale = height / 1080
    alignment = {"bottom": 2, "middle": 5, "top": 8}[style["position"]]
    if style["box"]:
        border_style = 3
        outline_colour = _ass_color(style["box_color"], style["box_opacity"])
        outline = max(round(10 * scale), 1)  # box padding
    else:
        border_style = 1
        outline_colour = _ass_color(style["outline_color"])
        outline = round(style["outline"] * scale, 1)
    fields = [
        "Default",
        style["font"],
        str(round(style["size"] * scale)),
        _ass_color(style["color"]),
        _ass_color(style["color"]),
        outline_colour,
        "&H80000000",
        "-1" if style["bold"] else "0",
        "0", "0", "0", "100", "100", "0", "0",
        str(border_style),
        str(outline),
        "0",
        str(alignment),
        str(round(40 * scale)),
        str(round(40 * scale)),
        str(round(style["margin"] * scale)),
        "1",
    ]
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: " + ",".join(fields),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for seg in segments:
        if not seg["text"].strip():
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(seg['start'])},{_ass_time(seg['end'])},Default,,0,0,0,,{_ass_text(seg['text'])}"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- parsing

_TIME_LINE = re.compile(
    r"(?P<s>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*(?P<e>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)


def _parse_time(value: str) -> float:
    value = value.replace(",", ".")
    parts = value.split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2])
    hours = int(parts[-3]) if len(parts) == 3 else 0
    return hours * 3600 + minutes * 60 + seconds


def parse_subtitles(content: str) -> list[dict]:
    """Parse SRT or WebVTT text into segments."""
    content = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    segments = []
    for block in re.split(r"\n\s*\n", content):
        lines = block.strip("\n").split("\n")
        for i, line in enumerate(lines):
            match = _TIME_LINE.search(line)
            if match:
                text = "\n".join(lines[i + 1 :]).strip()
                text = re.sub(r"<[^>]+>", "", text)  # drop VTT/SRT formatting tags
                segments.append(
                    {"start": _parse_time(match["s"]), "end": _parse_time(match["e"]), "text": text}
                )
                break
    return normalize_segments(segments)
