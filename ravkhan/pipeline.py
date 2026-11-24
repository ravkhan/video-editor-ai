"""RAVKHAN AI VIDEO — автоматический монтаж Instagram Reels.

Этапы для каждого видео из папки input/:
  1. Проверка исходника (SHA-256) — оригинал никогда не изменяется
  2. Анализ: разрешение, поворот, FPS, HDR
  3. Поиск и удаление длинных пауз (Auto-Editor)
  4. Анализ сцен (PySceneDetect) + поиск лиц для кадрирования 9:16
  5. Сборка звука, распознавание речи (Whisper), субтитры
  6. Музыка (по желанию) + нормализация громкости под Instagram
  7. Экспорт 1080p и/или 4K
  8. Превью и проверка качества, отчёт
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import cuts, quality, render, scenes, subtitles
from .probe import probe
from .utils import (AUDIO_EXT, ROOT, VIDEO_EXT, die, fmt_time, log, sha256, warn,
                    write_json)

INPUT, OUTPUT, SUBS, MUSIC, PREVIEWS = (ROOT / d for d in
                                        ("input", "output", "subtitles", "music", "previews"))


@dataclass
class Config:
    lang: str = "auto"
    whisper_model: str = "small"
    quality: str = "1080p"          # 1080p | 4k | both
    reframe: str = "face"           # face | center | blur
    speed: str = "balanced"         # fast | balanced | best
    codec: str = "h264"             # h264 | h265
    crf_1080: int = 17
    crf_4k: int = 18
    min_pause: float = 0.7
    pause_padding: float = 0.15
    silence_threshold: float = 0.04
    silence_db: float = -35.0
    scene_threshold: float = 3.0
    no_cut: bool = False
    subs: bool = True
    burn_subs: bool = True
    subs_style: str = "highlight"   # highlight | simple
    subs_max_chars: int = 30
    music: str | None = None        # None | auto | имя файла из music/
    music_volume: float = -18.0
    lufs: float = -14.0
    force: bool = False
    keep_work: bool = False


def safe_name(p: Path) -> str:
    n = re.sub(r"[^\w\-]+", "_", p.stem, flags=re.UNICODE).strip("_")
    return n or "video"


def find_music(cfg: Config) -> Path | None:
    if not cfg.music:
        return None
    tracks = sorted(p for p in MUSIC.iterdir() if p.suffix.lower() in AUDIO_EXT)
    if cfg.music == "auto":
        if not tracks:
            warn("В папке music/ нет треков — монтаж без музыки")
            return None
        return tracks[0]
    cand = Path(cfg.music)
    for p in (cand, MUSIC / cfg.music):
        if p.exists():
            return p
    warn(f"Музыка «{cfg.music}» не найдена — монтаж без музыки")
    return None


def process(src: Path, cfg: Config) -> dict:
    name = safe_name(src)
    out_dir = OUTPUT / name
    prev_dir = PREVIEWS / name
    targets = ["1080p", "4k"] if cfg.quality == "both" else [cfg.quality]
    finals = {r: out_dir / f"{name}_reels_{r}.mp4" for r in targets}
    if not cfg.force and all(p.exists() for p in finals.values()):
        log(f"«{src.name}» уже смонтирован — пропускаю (используйте --force для повтора)")
        return {"source": src.name, "status": "SKIPPED"}

    t_start = time.time()
    print(f"\n{'═' * 64}\n🎬  {src.name}\n{'═' * 64}", flush=True)
    log("Проверяю исходник и считаю контрольную сумму (SHA-256)…")
    hash_before = sha256(src)
    stat_before = src.stat()
    info = probe(src)
    log(f"Исходник: {info.width}x{info.height}, {info.src_fps:.2f} к/с → {float(info.fps):.3f}, "
        f"{fmt_time(info.duration)}, {info.vcodec} {info.bit_depth}-bit"
        f"{', HDR → SDR' if info.hdr else ''}{', поворот ' + str(info.rotation) if info.rotation else ''}"
        f"{'' if info.has_audio else ', БЕЗ ЗВУКА'}")

    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"ravkhan_{name}_"))
    report: dict = {"source": src.name, "source_sha256": hash_before,
                    "source_info": info.to_dict(), "config": asdict(cfg)}
    try:
        # 3. Паузы
        segs, cut_method = cuts.detect(src, work, info, cfg)
        kept = sum(e - s for s, e in segs)
        write_json(out_dir / f"{name}_edit_list.json",
                   {"method": cut_method, "kept_seconds": kept,
                    "segments": [{"start": round(s, 4), "end": round(e, 4)} for s, e in segs]})

        # 4. Сцены и кадрирование
        scene_list, scene_method = scenes.detect_scenes(src, info, cfg.scene_threshold)
        centers = scenes.crop_centers(src, info, scene_list, cfg.reframe)
        thumbs = scenes.scene_thumbnails(src, scene_list, prev_dir / "scenes")
        write_json(out_dir / f"{name}_scenes.json",
                   [{"n": i + 1, "start": round(s, 3), "end": round(e, 3), "crop_center": round(c, 3)}
                    for i, ((s, e), c) in enumerate(zip(scene_list, centers))])

        # 5. Звук и субтитры
        log("Собираю звук без пауз…")
        speech = render.build_speech(src, info, segs, work)
        subs_info = None
        if cfg.subs and info.has_audio:
            subs_info = subtitles.make_subtitles(render.speech_16k(speech, work), name, SUBS, cfg)

        # 6. Музыка и громкость
        music = find_music(cfg)
        if music:
            log(f"Музыка: {music.name} (громкость {cfg.music_volume} dB, приглушение под голос)")
        log(f"Нормализую громкость до {cfg.lufs} LUFS…")
        audio, loud = render.final_audio(speech, music, work, cfg, kept)

        # 7. Экспорт
        ass = None
        if subs_info and cfg.burn_subs:
            ass = work / "subs.ass"
            shutil.copy(subs_info["ass"], ass)
        geo = render.crop_geometry(info)
        results = {}
        for res in targets:
            W, H = render.TARGETS[res]
            upscale = (H / geo["ch"]) if cfg.reframe != "blur" else (W / info.width)
            if upscale > 1.05:
                warn(f"{res}: исходный кадр {geo['cw']}x{geo['ch']} будет увеличен в {upscale:.2f}×")
            log(f"Экспорт {res} ({W}x{H}, {cfg.codec}, CRF {cfg.crf_1080 if res == '1080p' else cfg.crf_4k}, "
                f"режим «{cfg.speed}»)…")
            render.encode(src, audio, finals[res], info, segs, scene_list, centers, res, cfg,
                          ass, work, kept)
            log(f"Проверка качества {res}…")
            qc = quality.check_output(finals[res], W=W, H=H, fps=info.fps, expected=kept,
                                      upscale=upscale, lufs_target=cfg.lufs)
            results[res] = {"file": str(finals[res].relative_to(ROOT)), **qc}
            log(f"Проверка {res}: {qc['status']}")

        # 8. Превью
        first = finals[targets[0]]
        pv = render.previews(first, prev_dir, name, kept)

        # Целостность исходника
        hash_after = sha256(src)
        st = src.stat()
        intact = hash_after == hash_before and st.st_size == stat_before.st_size \
            and st.st_mtime == stat_before.st_mtime
        report.update({
            "source_intact": intact, "source_sha256_after": hash_after,
            "cut_method": cut_method, "scene_method": scene_method,
            "duration_before": info.duration, "duration_after": kept,
            "segments": len(segs), "scenes": len(scene_list),
            "subtitles": {k: (str(v.relative_to(ROOT)) if isinstance(v, Path) else v)
                          for k, v in (subs_info or {}).items()},
            "music": music.name if music else None, "loudness_measured": loud,
            "outputs": results,
            "previews": [str(p.relative_to(ROOT)) for p in pv + thumbs[:3]],
            "processing_seconds": round(time.time() - t_start, 1),
        })
        statuses = [r["status"] for r in results.values()]
        report["status"] = "FAIL" if (not intact or "FAIL" in statuses) else (
            "WARN" if "WARN" in statuses else "PASS")
        write_json(out_dir / f"{name}_report.json", report)
        (out_dir / f"{name}_report.txt").write_text(human_report(report), encoding="utf-8")
        print(human_report(report), flush=True)
        if not intact:
            warn("ВНИМАНИЕ: контрольная сумма исходника изменилась!")
        return report
    finally:
        if cfg.keep_work:
            log(f"Временные файлы сохранены: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def human_report(r: dict) -> str:
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}
    si = r["source_info"]
    lines = [
        "", "─" * 64, f"ОТЧЁТ RAVKHAN AI VIDEO — {r['source']}", "─" * 64,
        f"Итог: {icon.get(r['status'], '')} {r['status']}",
        f"Исходник: {si['width']}x{si['height']}, {fmt_time(si['duration'])}, "
        f"{si['vcodec']}{' HDR' if si['hdr'] else ''}",
        f"Исходник не изменён: {'да ✅' if r['source_intact'] else 'НЕТ ❌'} "
        f"(SHA-256 {r['source_sha256'][:16]}…)",
        f"Длительность: {fmt_time(r['duration_before'])} → {fmt_time(r['duration_after'])} "
        f"(вырезано {r['duration_before'] - r['duration_after']:.1f}s пауз, склеек: {r['segments']})",
        f"Сцен найдено: {r['scenes']}",
    ]
    if r["subtitles"]:
        lines.append(f"Субтитры: язык «{r['subtitles'].get('language')}», "
                     f"{r['subtitles'].get('cues')} строк → {r['subtitles'].get('srt')}")
    else:
        lines.append("Субтитры: нет")
    lines.append(f"Музыка: {r['music'] or 'нет'}")
    for res, o in r["outputs"].items():
        m = o["meta"]
        lines.append(f"\n▶ {res}: {o['file']}  {icon[o['status']]} {o['status']}"
                     f"  ({m.get('size_mb')} МБ, {m.get('bitrate_mbps')} Мбит/с)")
        for st, name, det in o["checks"]:
            lines.append(f"   {icon[st]} {name}: {det}")
    lines.append("\nПревью: " + ", ".join(r["previews"][:3]))
    lines.append(f"Время обработки: {r['processing_seconds']}s")
    lines.append("─" * 64)
    return "\n".join(lines) + "\n"


def download(url: str) -> Path:
    INPUT.mkdir(exist_ok=True)
    log(f"Скачиваю видео: {url[:80]}…")
    before = set(INPUT.iterdir())
    if "drive.google.com" in url or "docs.google.com" in url:
        import gdown
        path = gdown.download(url, output=str(INPUT) + "/", quiet=False, fuzzy=True)
        if not path:
            die("Не удалось скачать с Google Drive. Откройте доступ «Всем, у кого есть ссылка».")
        return Path(path)
    if "dropbox.com" in url:
        url = re.sub(r"([?&])dl=0", r"\1dl=1", url)
        if "dl=1" not in url:
            url += ("&" if "?" in url else "?") + "dl=1"
    fname = re.sub(r"[?#].*$", "", url.rstrip("/").split("/")[-1]) or "video.mp4"
    if Path(fname).suffix.lower() not in VIDEO_EXT:
        fname += ".mp4"
    dest = INPUT / fname
    proc = subprocess.run(["curl", "-fL", "--retry", "3", "-o", str(dest), url])
    if proc.returncode != 0 or not dest.exists():
        die("Не удалось скачать видео по ссылке (нужна прямая ссылка на файл).")
    new = set(INPUT.iterdir()) - before
    return dest if dest in new or dest.exists() else next(iter(new))


def parse_args(argv=None) -> tuple[Config, argparse.Namespace]:
    p = argparse.ArgumentParser(
        prog="montage.sh", description="RAVKHAN AI VIDEO — автоматический монтаж Reels",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("files", nargs="*", help="видео (по умолчанию — все из папки input/)")
    p.add_argument("--url", action="append", default=[],
                   help="скачать видео по ссылке (Google Drive, Dropbox, прямая ссылка)")
    p.add_argument("--lang", default="auto", help="язык речи: auto, ru, ar, en …")
    p.add_argument("--model", dest="whisper_model", default="small",
                   choices=["tiny", "base", "small", "medium", "large-v3", "turbo"],
                   help="модель Whisper: точнее = медленнее")
    p.add_argument("--quality", default="1080p", choices=["1080p", "4k", "both"])
    p.add_argument("--reframe", default="face", choices=["face", "center", "blur"],
                   help="face — по лицу, center — по центру, blur — весь кадр на размытом фоне")
    p.add_argument("--speed", default="balanced", choices=["fast", "balanced", "best"])
    p.add_argument("--codec", default="h264", choices=["h264", "h265"])
    p.add_argument("--crf", type=int, default=None, help="качество 1080p (меньше = лучше, 14–23)")
    p.add_argument("--min-pause", type=float, default=0.7, help="удалять паузы длиннее (сек)")
    p.add_argument("--padding", dest="pause_padding", type=float, default=0.15,
                   help="сколько тишины оставлять у краёв паузы (сек)")
    p.add_argument("--threshold", dest="silence_threshold", type=float, default=0.04,
                   help="порог тишины Auto-Editor (0.01–0.1)")
    p.add_argument("--no-cut", action="store_true", help="не удалять паузы")
    p.add_argument("--no-subs", action="store_true", help="без субтитров")
    p.add_argument("--no-burn", action="store_true", help="субтитры только файлом, не в видео")
    p.add_argument("--subs-style", default="highlight", choices=["highlight", "simple"])
    p.add_argument("--music", default=None, help="'auto' или имя файла из music/")
    p.add_argument("--music-volume", type=float, default=-18.0, help="громкость музыки (dB)")
    p.add_argument("--force", action="store_true", help="перемонтировать уже готовые")
    p.add_argument("--keep-work", action="store_true", help="не удалять временные файлы")
    a = p.parse_args(argv)
    cfg = Config(lang=a.lang, whisper_model=a.whisper_model, quality=a.quality,
                 reframe=a.reframe, speed=a.speed, codec=a.codec,
                 crf_1080=a.crf if a.crf is not None else 17,
                 crf_4k=(a.crf + 1) if a.crf is not None else 18,
                 min_pause=a.min_pause, pause_padding=a.pause_padding,
                 silence_threshold=a.silence_threshold, no_cut=a.no_cut,
                 subs=not a.no_subs, burn_subs=not a.no_burn, subs_style=a.subs_style,
                 music=a.music, music_volume=a.music_volume, force=a.force,
                 keep_work=a.keep_work)
    return cfg, a


def main(argv=None) -> int:
    cfg, a = parse_args(argv)
    for d in (INPUT, OUTPUT, SUBS, MUSIC, PREVIEWS):
        d.mkdir(exist_ok=True)
    files = [Path(f).resolve() for f in a.files]
    for url in a.url:
        files.append(download(url))
    if not files:
        files = sorted(p for p in INPUT.iterdir()
                       if p.is_file() and p.suffix.lower() in VIDEO_EXT)
    if not files:
        die("Нет видео. Положите файл в папку input/ или укажите --url ССЫЛКА")
    for f in files:
        if not f.exists():
            die(f"Файл не найден: {f}")

    print(f"RAVKHAN AI VIDEO — видео к монтажу: {len(files)}", flush=True)
    results = []
    for f in files:
        try:
            results.append(process(f, cfg))
        except Exception as exc:  # noqa: BLE001
            print(f"\n❌ «{f.name}»: монтаж не удался — {exc}", file=sys.stderr, flush=True)
            results.append({"source": f.name, "status": "ERROR"})

    print("\n" + "═" * 64 + "\nИТОГО", flush=True)
    for r in results:
        print(f"  {r['status']:8} {r['source']}")
    print("Готовые ролики: output/   Субтитры: subtitles/   Превью: previews/\n", flush=True)
    return 1 if any(r["status"] in ("ERROR", "FAIL") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
