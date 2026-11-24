"""Проверка качества готового ролика и целостности исходника."""
from __future__ import annotations

import re
from pathlib import Path

from .utils import ffprobe, parse_rate, run


def check_output(path: Path, *, W: int, H: int, fps, expected: float, upscale: float,
                 lufs_target: float) -> dict:
    checks: list[tuple[str, str, str]] = []  # (статус, проверка, детали)

    def add(ok: bool | None, name: str, detail: str) -> None:
        checks.append(("PASS" if ok else ("WARN" if ok is None else "FAIL"), name, detail))

    if not path.exists() or path.stat().st_size == 0:
        add(False, "Файл создан", "файл отсутствует или пустой")
        return _summary(checks, {})

    data = ffprobe(path)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    dur = float(data["format"].get("duration", 0))
    br = int(data["format"].get("bit_rate", 0))
    meta = {"duration": dur, "bitrate_mbps": round(br / 1e6, 2),
            "size_mb": round(path.stat().st_size / 1e6, 1)}

    add(v is not None and (int(v["width"]), int(v["height"])) == (W, H),
        "Разрешение", f"{v and v['width']}x{v and v['height']} (нужно {W}x{H})")
    add(v is not None and v["codec_name"] in ("h264", "hevc") and v.get("pix_fmt") == "yuv420p",
        "Видеокодек", f"{v and v['codec_name']} {v and v.get('pix_fmt')}")
    vf = float(parse_rate(v.get("avg_frame_rate"))) if v else 0
    add(abs(vf - float(fps)) < 0.05, "Частота кадров", f"{vf:.3f} (нужно {float(fps):.3f})")
    add(a is not None and a["codec_name"] == "aac", "Звук", f"{a and a['codec_name']} "
        f"{a and a.get('sample_rate')} Гц, {a and a.get('channels')} кан.")
    frame = 1 / float(fps)
    add(abs(dur - expected) <= max(0.1, 2 * frame), "Длительность",
        f"{dur:.2f}s (ожидалось {expected:.2f}s)")
    if v is not None and a is not None:
        vd, ad = float(v.get("duration", dur)), float(a.get("duration", dur))
        add(abs(vd - ad) <= 0.1, "Синхронность A/V", f"видео {vd:.2f}s / звук {ad:.2f}s")
    add(dur <= 180 or None, "Длина для Reels", f"{dur:.1f}s (Reels до 3 минут)")

    # полный проход декодера: битые кадры, чёрные участки, громкость
    proc = run(["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", str(path),
                "-filter_complex", "[0:v]blackdetect=d=1.0:pix_th=0.08[v];[0:a]ebur128=peak=true[a]",
                "-map", "[v]", "-map", "[a]", "-f", "null", "-"], check=False)
    errs = [ln for ln in proc.stderr.splitlines()
            if re.search(r"(error|corrupt|invalid|concealing)", ln, re.I) and "ebur128" not in ln]
    add(proc.returncode == 0 and not errs, "Декодирование без ошибок",
        "ok" if not errs else errs[0][:120])
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", proc.stderr)
    add(None if blacks else True, "Чёрные кадры",
        "нет" if not blacks else f"{len(blacks)} участк. (первый с {float(blacks[0][0]):.1f}s)")
    summ = proc.stderr[proc.stderr.rfind("Summary:"):] if "Summary:" in proc.stderr else ""
    mi = re.search(r"I:\s+(-?[\d.]+) LUFS", summ)
    mp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ)
    if mi:
        lufs = float(mi.group(1))
        meta["lufs"] = lufs
        ok = True if abs(lufs - lufs_target) <= 2 else (None if lufs < -50 else False)
        add(ok, "Громкость",
            f"{lufs:.1f} LUFS (цель {lufs_target})")
    if mp:
        peak = float(mp.group(1))
        meta["true_peak"] = peak
        add(peak <= -0.5, "Пиковый уровень", f"{peak:.1f} dBTP (не клиппирует)")

    if upscale > 1.05:
        add(None, "Детализация исходника",
            f"исходный кадр увеличен в {upscale:.2f}× — чётче не будет, чем в оригинале")
    else:
        add(True, "Детализация исходника", f"без увеличения (масштаб {upscale:.2f}×)")
    add(True, "Битрейт", f"{br / 1e6:.1f} Мбит/с (CRF: битрейт зависит от сложности кадра)")
    return _summary(checks, meta)


def _summary(checks, meta) -> dict:
    status = "FAIL" if any(c[0] == "FAIL" for c in checks) else (
        "WARN" if any(c[0] == "WARN" for c in checks) else "PASS")
    return {"status": status, "checks": checks, "meta": meta}
