#!/usr/bin/env bash
# Диагностика: проверяет, что все программы реально установлены и работают.
cd "$(dirname "$0")"
ok=0; fail=0
pass() { echo "  ✅ $1"; ok=$((ok+1)); }
bad()  { echo "  ❌ $1"; fail=$((fail+1)); }
PY=.venv/bin/python
echo "RAVKHAN AI VIDEO — проверка системы"
v=$(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}') && [ -n "$v" ] && pass "FFmpeg $v" || bad "FFmpeg не найден"
for e in libx264 libx265 aac; do ffmpeg -hide_banner -encoders 2>/dev/null | grep -q " $e " && pass "кодек $e" || bad "нет кодека $e"; done
for f in ass loudnorm sidechaincompress zscale ebur128; do ffmpeg -hide_banner -filters 2>/dev/null | grep -q " $f " && pass "фильтр $f" || bad "нет фильтра $f"; done
v=$(.venv/bin/auto-editor --version 2>/dev/null) && pass "Auto-Editor $v" || bad "Auto-Editor не работает"
v=$($PY -c "import whisper;print(whisper.__version__)" 2>/dev/null) && pass "OpenAI Whisper $v" || bad "Whisper не установлен"
v=$($PY -c "import torch;print(torch.__version__)" 2>/dev/null) && pass "PyTorch $v" || bad "PyTorch не установлен"
v=$($PY -c "import scenedetect;print(scenedetect.__version__)" 2>/dev/null) && pass "PySceneDetect $v" || bad "PySceneDetect не установлен"
$PY -c "import cv2;cv2.FaceDetectorYN.create('models/face_detection_yunet_2023mar.onnx','',(320,320))" 2>/dev/null && pass "детектор лиц YuNet" || bad "детектор лиц (models/face_detection_yunet_2023mar.onnx)"
ls models/*.pt >/dev/null 2>&1 && pass "модели Whisper: $(cd models && ls *.pt | tr '\n' ' ')" || echo "  ⚪ модели Whisper скачаются при первом монтаже"
fc-list | grep -q "Noto Sans Arabic" && pass "шрифт для арабских субтитров" || bad "нет шрифта Noto Sans Arabic"
fc-list | grep -q "Noto Sans:style=Bold" && pass "шрифт для русских субтитров" || bad "нет шрифта Noto Sans"
for d in input output subtitles music previews; do [ -d $d ] || bad "нет папки $d"; done
echo "Процессоров: $(nproc), память: $(free -h | awk '/Mem/{print $2}'), свободно на диске: $(df -h . | awk 'NR==2{print $4}')"
echo "Итог: $ok проверок пройдено, $fail ошибок"
[ $fail -eq 0 ]
