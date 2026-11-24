"""Общие утилиты: запуск команд, логирование, ffprobe, хэши."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = ROOT / ".venv" / "bin"

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts", ".3gp", ".hevc"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

_t0 = time.time()


def log(msg: str, level: str = "•") -> None:
    elapsed = time.time() - _t0
    print(f"[{elapsed:6.1f}s] {level} {msg}", flush=True)


def warn(msg: str) -> None:
    log(msg, "⚠️ ")


def die(msg: str, code: int = 1) -> None:
    print(f"\n❌ ОШИБКА: {msg}\n", file=sys.stderr, flush=True)
    sys.exit(code)


def tool(name: str) -> str:
    """Путь к программе: сначала из .venv, затем из системы."""
    local = VENV_BIN / name
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if not found:
        die(f"Программа '{name}' не найдена. Запустите ./setup.sh")
    return found


def run(cmd: list[str], *, capture: bool = True, check: bool = True,
        quiet_error: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=capture, text=True)
    if check and proc.returncode != 0:
        if not quiet_error:
            tail = (proc.stderr or "")[-3000:]
            print(f"\nКоманда завершилась с ошибкой ({proc.returncode}):\n  "
                  f"{' '.join(cmd[:6])} ...\n{tail}", file=sys.stderr)
        raise RuntimeError(f"command failed: {cmd[0]}")
    return proc


def sha256(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def ffprobe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)]).stdout
    return json.loads(out)


def parse_rate(s: str | None) -> Fraction:
    if not s or s in ("0/0", "0"):
        return Fraction(0)
    try:
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def fmt_time(sec: float) -> str:
    m, s = divmod(max(sec, 0), 60)
    return f"{int(m)}:{s:05.2f}"


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
