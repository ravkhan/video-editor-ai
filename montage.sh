#!/usr/bin/env bash
# RAVKHAN AI VIDEO — монтаж одной командой.
#   ./montage.sh                     — смонтировать все видео из input/
#   ./montage.sh --lang ar           — арабская речь
#   ./montage.sh --quality both      — 1080p + 4K
#   ./montage.sh --help              — все настройки
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ] || ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Первый запуск: устанавливаю программы (5–10 минут)…"
  ./setup.sh
fi
exec .venv/bin/python -m ravkhan "$@"
