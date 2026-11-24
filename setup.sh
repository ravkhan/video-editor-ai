#!/usr/bin/env bash
# Установка всех компонентов RAVKHAN AI VIDEO. Можно запускать повторно.
set -euo pipefail
cd "$(dirname "$0")"
SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null && SUDO="sudo"

echo "▶ 1/5 Системные пакеты: FFmpeg, шрифты для кириллицы и арабского"
need=""
command -v ffmpeg  >/dev/null || need="$need ffmpeg"
fc-list 2>/dev/null | grep -q "Noto Sans Arabic" || need="$need fonts-noto-core"
command -v curl    >/dev/null || need="$need curl"
if [ -n "$need" ]; then
  $SUDO apt-get update -qq && $SUDO apt-get install -y -qq $need
fi

echo "▶ 2/5 Python-окружение (.venv)"
if ! command -v uv >/dev/null && [ -x "$HOME/.local/bin/uv" ]; then export PATH="$HOME/.local/bin:$PATH"; fi
if command -v uv >/dev/null; then
  [ -x .venv/bin/python ] || uv venv .venv --python 3.12 -q
  PIP="uv pip install --python .venv/bin/python -q"
else
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/python -m pip install -q --upgrade pip
  PIP=".venv/bin/python -m pip install -q"
fi

echo "▶ 3/5 PyTorch (CPU) + Whisper + Auto-Editor + PySceneDetect"
.venv/bin/python -c "import torch" 2>/dev/null || $PIP torch --index-url https://download.pytorch.org/whl/cpu
$PIP -r requirements.txt
# auto-editor скачивает свой бинарник при первом запуске
.venv/bin/auto-editor --version >/dev/null

echo "▶ 4/5 Модели: детектор лиц YuNet и Whisper small"
mkdir -p models input output subtitles music previews
[ -s models/face_detection_yunet_2023mar.onnx ] || curl -fsSL -o models/face_detection_yunet_2023mar.onnx \
  https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
[ -s models/small.pt ] || .venv/bin/python -c "import whisper; whisper.load_model('small', download_root='models')"

echo "▶ 5/5 Проверка"
./check.sh
