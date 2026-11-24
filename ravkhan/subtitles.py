"""Распознавание речи (OpenAI Whisper) и создание субтитров SRT / ASS / TXT.
Поддерживаются русский, арабский и автоопределение языка."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .utils import ROOT, log, warn

SENTENCE_END = re.compile(r"[.!?…؟。]$")
CLAUSE_END = re.compile(r"[,;:،؛]$")

FONTS = {"ar": "Noto Sans Arabic", "fa": "Noto Sans Arabic", "ur": "Noto Sans Arabic"}
# Языки с письмом справа налево: подсветка слов цветом ломает порядок слов в libass,
# поэтому для них всегда используется простой стиль (проверено визуально).
RTL = {"ar", "fa", "ur", "he", "yi", "ps"}
# Иероглифы/кана в русской или арабской речи — почти всегда «галлюцинация» Whisper
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
DEFAULT_FONT = "Noto Sans"
PROMPTS = {  # подсказка Whisper ставить пунктуацию
    "ru": "Привет. Сегодня расскажу, как это работает.",
    "ar": "مرحبا. اليوم سأشرح لكم كيف يعمل هذا.",
}


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Cue:
    start: float
    end: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def transcribe(audio16k: Path, lang: str, model_name: str) -> tuple[list[Word], str]:
    import whisper  # тяжёлый импорт — только когда нужен

    log(f"Whisper: загружаю модель «{model_name}» (первый раз — скачивание)…")
    model = whisper.load_model(model_name, device="cpu", download_root=str(ROOT / "models"))
    language = None if lang == "auto" else lang
    log("Whisper: распознаю речь…")
    res = model.transcribe(
        str(audio16k), language=language, task="transcribe", fp16=False,
        word_timestamps=True, condition_on_previous_text=False,
        initial_prompt=PROMPTS.get(language or "", None), verbose=None,
    )
    detected = res.get("language") or language or "unknown"
    words: list[Word] = []
    for seg in res.get("segments", []):
        # отбрасываем «галлюцинации» на тишине
        if seg.get("no_speech_prob", 0) > 0.6 and seg.get("avg_logprob", 0) < -1.0:
            continue
        for w in seg.get("words", []) or []:
            txt = w["word"].strip()
            if txt and not (detected in ("ru", "ar", "en") and CJK.search(txt)):
                words.append(Word(float(w["start"]), float(w["end"]), txt))
    log(f"Whisper: язык = {detected}, слов = {len(words)}")
    return words, detected


def group_cues(words: list[Word], max_chars: int, max_dur: float = 3.2,
               max_gap: float = 0.6) -> list[Cue]:
    cues: list[Cue] = []
    cur: list[Word] = []

    def flush():
        if cur:
            cues.append(Cue(cur[0].start, cur[-1].end, list(cur)))
            cur.clear()

    for w in words:
        if cur:
            length = len(" ".join(x.text for x in cur)) + 1 + len(w.text)
            if (length > max_chars or w.end - cur[0].start > max_dur
                    or w.start - cur[-1].end > max_gap):
                flush()
        cur.append(w)
        if SENTENCE_END.search(w.text) or (CLAUSE_END.search(w.text)
                                           and len(" ".join(x.text for x in cur)) > max_chars * 0.5):
            flush()
    flush()
    # субтитр держится до следующего (без мигания), но не дольше +0.5 с
    for i, c in enumerate(cues):
        nxt = cues[i + 1].start if i + 1 < len(cues) else c.end + 0.5
        c.end = max(c.end, min(nxt, c.end + 0.5))
        if c.end - c.start < 0.4:
            c.end = c.start + 0.4
    return cues


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def write_srt(cues: list[Cue], path: Path) -> None:
    lines = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{_srt_time(c.start)} --> {_srt_time(c.end)}", c.text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_ass(cues: list[Cue], path: Path, lang: str, style: str,
              W: int = 1080, H: int = 1920) -> None:
    font = FONTS.get(lang, DEFAULT_FONT)
    size = int(H * (0.046 if lang in FONTS else 0.042))
    outline = max(2, int(H * 0.0035))
    margin_v = int(H * 0.24)   # выше интерфейса Instagram (подпись, кнопки)
    margin_lr = int(W * 0.08)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Reels,{font},{size},&H00FFFFFF,&H0000E5FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},{max(1, outline // 2)},2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if lang in RTL:
        style = "simple"
    ev = []
    hl = "{\\c&H0000E5FF&}"
    for c in cues:
        if style == "highlight" and len(c.words) > 1:
            # активное слово подсвечивается жёлтым
            for j, w in enumerate(c.words):
                s = c.start if j == 0 else w.start
                e = c.words[j + 1].start if j + 1 < len(c.words) else c.end
                if e <= s:
                    continue
                parts = [(hl + _ass_escape(x.text) + "{\\c&H00FFFFFF&}") if k == j
                         else _ass_escape(x.text) for k, x in enumerate(c.words)]
                ev.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Reels,,0,0,0,,{' '.join(parts)}")
        else:
            ev.append(f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},Reels,,0,0,0,,"
                      f"{_ass_escape(c.text)}")
    path.write_text(header + "\n".join(ev) + "\n", encoding="utf-8")


def make_subtitles(audio16k: Path, name: str, out_dir: Path, cfg) -> dict | None:
    try:
        words, lang = transcribe(audio16k, cfg.lang, cfg.whisper_model)
    except Exception as exc:  # noqa: BLE001
        warn(f"Распознавание речи не удалось: {exc}")
        return None
    if not words:
        warn("Речь не найдена — субтитры не созданы")
        return None
    cues = group_cues(words, cfg.subs_max_chars)
    out_dir.mkdir(parents=True, exist_ok=True)
    srt, ass, txt = (out_dir / f"{name}.srt", out_dir / f"{name}.ass", out_dir / f"{name}.txt")
    write_srt(cues, srt)
    write_ass(cues, ass, lang, cfg.subs_style)
    txt.write_text("\n".join(c.text for c in cues) + "\n", encoding="utf-8")
    log(f"Субтитры: {len(cues)} строк → {srt.name}, {ass.name}, {txt.name}")
    return {"srt": srt, "ass": ass, "txt": txt, "language": lang, "cues": len(cues)}
