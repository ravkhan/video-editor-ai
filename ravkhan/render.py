"""Сборка звука и видео: склейка без пауз, кадрирование 9:16, субтитры,
музыка с приглушением под голос, нормализация громкости, экспорт 1080p / 4K."""
from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np

from .utils import log, run, warn

SR = 48000
FADE = int(SR * 0.008)  # 8 мс — микро-переход на склейках против щелчков

PRESETS = {"fast": ("veryfast", "fast"), "balanced": ("slow", "medium"), "best": ("slower", "slow")}
TARGETS = {"1080p": (1080, 1920), "4k": (2160, 3840)}


# ───────────────────────────── ЗВУК ─────────────────────────────

def build_speech(src: Path, info, segs, work: Path) -> Path:
    """Вырезает фрагменты звука с точностью до сэмпла (синхронно с кадрами)."""
    out = work / "speech.wav"
    total = sum(e - s for s, e in segs)
    if not info.has_audio:
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             f"anullsrc=r={SR}:cl=stereo", "-t", f"{total:.6f}", "-c:a", "pcm_s24le", str(out)])
        return out
    raw = run_bytes(["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:a:0",
                     "-af", "aresample=async=1:first_pts=0", "-ac", "2", "-ar", str(SR),
                     "-f", "f32le", "-"])
    audio = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
    ramp = np.linspace(0, 1, FADE, dtype=np.float32)[:, None]
    parts = []
    for s, e in segs:
        a, b = int(round(s * SR)), int(round(e * SR))
        chunk = audio[a:b].copy()
        if len(chunk) < b - a:  # звук короче видео — добиваем тишиной
            chunk = np.vstack([chunk, np.zeros((b - a - len(chunk), 2), np.float32)])
        if len(chunk) > 2 * FADE and len(segs) > 1:
            chunk[:FADE] *= ramp
            chunk[-FADE:] *= ramp[::-1]
        parts.append(chunk)
    joined = np.concatenate(parts) if parts else np.zeros((0, 2), np.float32)
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR),
                          "-ac", "2", "-i", "-", "-c:a", "pcm_s24le", str(out)],
                         stdin=subprocess.PIPE)
    p.communicate(joined.tobytes())
    if p.returncode != 0:
        raise RuntimeError("не удалось записать звук")
    return out


def run_bytes(cmd: list[str]) -> bytes:
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="ignore")[-2000:])
    return proc.stdout


def speech_16k(speech: Path, work: Path) -> Path:
    out = work / "speech_16k.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(speech), "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(out)])
    return out


def final_audio(speech: Path, music: Path | None, work: Path, cfg, duration: float) -> tuple[Path, dict]:
    """Музыка (с автоприглушением под голос) + двухпроходная нормализация EBU R128."""
    mixed = work / "mixed.wav"
    if music:
        fade_st = max(0.0, duration - 2.0)
        fc = (f"[1:a]aresample={SR},aformat=channel_layouts=stereo,volume={cfg.music_volume}dB,"
              f"afade=t=in:d=1,afade=t=out:st={fade_st:.3f}:d=2[m];"
              f"[0:a]asplit=2[v][sc];"
              f"[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
              f"[v][duck]amix=inputs=2:duration=first:normalize=0[out]")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(speech), "-stream_loop", "-1",
             "-i", str(music), "-filter_complex", fc, "-map", "[out]", "-t", f"{duration:.6f}",
             "-c:a", "pcm_s24le", str(mixed)])
    else:
        mixed = speech

    target = f"I={cfg.lufs}:TP=-1.5:LRA=11"
    p1 = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mixed), "-af",
              f"loudnorm={target}:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p1.stderr, re.S)
    out = work / "final_audio.wav"
    if m:
        st = json.loads(m.group(0))
        if float(st.get("input_i", "-70")) < -60:  # почти тишина — не усиливаем шум
            af = "anull"
        else:
            af = (f"loudnorm={target}:measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
                  f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:"
                  f"offset={st['target_offset']}:linear=true")
    else:
        st, af = {}, f"loudnorm={target}"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(mixed), "-af", f"{af},aresample={SR}",
         "-c:a", "pcm_s24le", str(out)])
    return out, st


# ───────────────────────────── ВИДЕО ─────────────────────────────

def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def crop_geometry(info) -> dict:
    W0, H0 = info.width, info.height
    if W0 / H0 > 9 / 16:
        ch = H0 - H0 % 2
        cw = min(_even(ch * 9 / 16), W0 - W0 % 2)
    else:
        cw = W0 - W0 % 2
        ch = min(_even(cw * 16 / 9), H0 - H0 % 2)
    return {"cw": cw, "ch": ch, "y": (H0 - ch) // 2 // 2 * 2, "W0": W0, "H0": H0}


def _crop_x_expr(geo, scenes, centers) -> str:
    maxx = geo["W0"] - geo["cw"]
    if maxx <= 0:
        return "0"
    xs = [min(max(int(round(c * geo["W0"] - geo["cw"] / 2)), 0), maxx) // 2 * 2 for c in centers]
    # объединяем соседние сцены с одинаковой позицией
    merged = []
    for (s, e), x in zip(scenes, xs):
        if merged and merged[-1][2] == x:
            merged[-1][1] = e
        else:
            merged.append([s, e, x])
    if len(merged) == 1:
        return str(merged[0][2])
    merged[0][0], merged[-1][1] = -1.0, 1e9
    terms = [f"{x}*gte(t,{s:.4f})*lt(t,{e:.4f})" for s, e, x in merged if x]
    return "+".join(terms) or "0"


def _select_expr(segs, fps: Fraction) -> str:
    h = 0.5 / float(fps)
    return "+".join(f"between(t,{s - h:.5f},{e - h - 1e-4:.5f})" for s, e in segs)


HDR_CHAIN = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
             "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def video_filter(info, segs, scenes, centers, W: int, H: int, mode: str,
                 ass: Path | None, tonemap: bool) -> str:
    F = info.fps
    geo = crop_geometry(info)
    pre = [HDR_CHAIN] if tonemap else []
    pre += [f"fps={F.numerator}/{F.denominator}", f"select='{_select_expr(segs, F)}'"]
    setpts = f"setpts=N/({F.numerator}/{F.denominator})/TB"
    scale_flags = "flags=lanczos+accurate_rnd+full_chroma_int:out_color_matrix=bt709"
    chain = "[0:v:0]" + ",".join(pre)
    if mode == "blur":
        chain += (f",{setpts},split[fg][bg];"
                  f"[bg]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,"
                  f"crop={W // 4}:{H // 4},gblur=sigma=12,eq=brightness=-0.06,"
                  f"scale={W}:{H}:flags=bicubic[bgb];"
                  f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:{scale_flags}[fgs];"
                  f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2")
    else:
        # crop стоит ДО setpts: позиция кадра зависит от исходного времени сцены
        x = _crop_x_expr(geo, scenes, centers)
        chain += (f",crop=w={geo['cw']}:h={geo['ch']}:x='{x}':y={geo['y']}:exact=1,"
                  f"{setpts},scale={W}:{H}:{scale_flags}")
    chain += ",setsar=1"
    if ass:
        chain += f",ass='{ass.as_posix()}'"
    chain += ",format=yuv420p[vout]"
    return chain


def encode(src: Path, audio: Path, out: Path, info, segs, scenes, centers, res: str,
           cfg, ass: Path | None, work: Path, expected: float) -> Path:
    W, H = TARGETS[res]
    vpreset = PRESETS[cfg.speed][0 if res == "1080p" else 1]
    crf = cfg.crf_1080 if res == "1080p" else cfg.crf_4k

    def attempt(tonemap: bool) -> None:
        script = work / f"filter_{res}.txt"
        script.write_text(video_filter(info, segs, scenes, centers, W, H, cfg.reframe,
                                       ass, tonemap), encoding="utf-8")
        if cfg.codec == "h265":
            vc = ["-c:v", "libx265", "-preset", vpreset, "-crf", str(crf + 2),
                  "-tag:v", "hvc1", "-x265-params", "log-level=error"]
        else:
            vc = ["-c:v", "libx264", "-preset", vpreset, "-crf", str(crf),
                  "-profile:v", "high", "-maxrate", "30M" if res == "1080p" else "90M",
                  "-bufsize", "60M" if res == "1080p" else "180M"]
        F = info.fps
        cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-v", "error",
               "-progress", "pipe:1", "-i", str(src), "-i", str(audio),
               "-filter_complex_script", str(script), "-map", "[vout]", "-map", "1:a:0",
               *vc, "-r", f"{F.numerator}/{F.denominator}",
               "-g", str(int(round(float(F) * 2))), "-pix_fmt", "yuv420p",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-color_range", "tv",
               "-c:a", "aac", "-b:a", "320k", "-ar", str(SR), "-ac", "2",
               "-shortest", "-movflags", "+faststart",
               "-metadata", "comment=RAVKHAN AI VIDEO", str(out)]
        _run_with_progress(cmd, expected, f"Экспорт {res}")

    try:
        attempt(info.hdr)
    except RuntimeError:
        if not info.hdr:
            raise
        warn("HDR-тонмаппинг не удался, повтор без него")
        attempt(False)
    return out


def _run_with_progress(cmd: list[str], expected: float, label: str) -> None:
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    last = -10
    assert p.stdout
    for line in p.stdout:
        if line.startswith("out_time_us=") and expected > 0:
            try:
                pct = int(int(line.split("=")[1]) / 1e6 / expected * 100)
            except ValueError:
                continue
            if pct >= last + 10:
                last = pct - pct % 10
                log(f"{label}: {min(last, 100)}%")
    err = p.stderr.read() if p.stderr else ""
    p.wait()
    if p.returncode != 0:
        print(err[-3000:])
        raise RuntimeError(f"{label}: ffmpeg error")


# ──────────────────────────── ПРЕВЬЮ ────────────────────────────

def previews(video: Path, out_dir: Path, name: str, duration: float) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    small = out_dir / f"{name}_preview_540p.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", "scale=540:960",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k",
         "-movflags", "+faststart", str(small)])
    sheet = out_dir / f"{name}_contact_sheet.jpg"
    step = max(duration / 12, 0.5)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf",
         f"fps=1/{step:.3f},scale=270:480,tile=6x2:padding=6:margin=6", "-frames:v", "1",
         "-q:v", "3", str(sheet)], check=False)
    cover = out_dir / f"{name}_cover.jpg"
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{min(1.0, duration / 3):.2f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "2", str(cover)], check=False)
    return [p for p in (small, sheet, cover) if p.exists()]
