"""Speech recognition with faster-whisper."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from . import config
from .subtitles import Word

SAMPLE_RATE = 16000


def load_audio(path: Path) -> np.ndarray:
    """Decode the first audio track to 16 kHz mono float32 with FFmpeg.

    Done here instead of by faster-whisper, whose PyAV-based decoder breaks
    with some PyAV versions.
    """
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-vn",
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


class Transcriber(Protocol):
    def transcribe(
        self,
        path: Path,
        model: str,
        language: str | None,
        task: str,
        on_progress: Callable[[float], None],
    ) -> tuple[list[Word], str]:
        """Return word-level timestamps and the detected language."""
        ...


class WhisperTranscriber:
    def __init__(self) -> None:
        self._models: dict[str, object] = {}
        self._lock = threading.Lock()

    def _get_model(self, name: str):
        with self._lock:
            if name not in self._models:
                from faster_whisper import WhisperModel

                self._models[name] = WhisperModel(
                    name, device=config.WHISPER_DEVICE, compute_type=config.WHISPER_COMPUTE_TYPE
                )
            return self._models[name]

    def transcribe(self, path, model, language, task, on_progress):
        whisper = self._get_model(model)
        segments, info = whisper.transcribe(
            load_audio(path),
            language=language or None,
            task=task,
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
        )
        words: list[Word] = []
        for segment in segments:  # generator: decoding happens while iterating
            for w in segment.words or []:
                words.append(Word(start=w.start, end=w.end, text=w.word))
            if info.duration:
                on_progress(min(segment.end / info.duration, 1.0))
        return words, info.language
