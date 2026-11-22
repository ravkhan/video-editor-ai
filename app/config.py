"""Runtime configuration, read from environment variables."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
PROJECTS_DIR = DATA_DIR / "projects"

# faster-whisper settings
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")  # "cpu", "cuda" or "auto"
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "default")  # e.g. "int8", "float16"
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3", "turbo"]
DEFAULT_WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "2048")) * 1024 * 1024
WORKERS = int(os.environ.get("WORKERS", "2"))

# Fonts offered in the UI. They must be installed on the server for burn-in.
FONTS = ["DejaVu Sans", "DejaVu Serif", "Inter", "FreeSans", "FreeSerif"]
