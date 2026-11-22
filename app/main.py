"""FastAPI application: REST API + static single-page editor."""

from __future__ import annotations

import shutil
import time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, media
from .storage import NotFound, Store
from .subtitles import (
    build_cues,
    normalize_segments,
    normalize_style,
    parse_subtitles,
    to_ass,
    to_srt,
    to_vtt,
)
from .transcriber import Transcriber, WhisperTranscriber

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_CHUNK = 1024 * 1024


class TranscribeRequest(BaseModel):
    model: str = config.DEFAULT_WHISPER_MODEL
    language: str | None = None  # None = auto-detect
    task: Literal["transcribe", "translate"] = "transcribe"
    max_chars: int = Field(84, ge=10, le=200)
    max_line: int = Field(42, ge=10, le=100)


class SegmentIn(BaseModel):
    id: str | None = None
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str = Field("", max_length=2000)


class SegmentsUpdate(BaseModel):
    segments: list[SegmentIn] = Field(max_length=20000)


def public(meta: dict) -> dict:
    """Project metadata as returned to the client."""
    return {k: v for k, v in meta.items() if k != "source"}


def create_app(data_dir: Path | None = None, transcriber: Transcriber | None = None) -> FastAPI:
    store = Store((data_dir or config.DATA_DIR) / "projects")
    stt: Transcriber = transcriber or WhisperTranscriber()
    executor = ThreadPoolExecutor(max_workers=config.WORKERS, thread_name_prefix="job")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Video Editor AI", lifespan=lifespan)
    app.state.store = store
    app.state.executor = executor

    def get_meta(project_id: str) -> dict:
        try:
            return store.get(project_id)
        except NotFound:
            raise HTTPException(404, "Проект не найден")

    def start_job(project_id: str, kind: str, fn, *args) -> None:
        meta = get_meta(project_id)
        if meta["jobs"].get(kind, {}).get("status") in ("queued", "running"):
            raise HTTPException(409, "Задача уже выполняется")
        store.set_job(project_id, kind, status="queued", progress=0.0, error=None, started=time.time())

        def run() -> None:
            store.set_job(project_id, kind, status="running")
            last = [0.0]

            def progress(value: float) -> None:
                if value - last[0] >= 0.01 or value >= 1.0:  # avoid excessive disk writes
                    last[0] = value
                    store.set_job(project_id, kind, progress=round(value, 3))

            try:
                fn(project_id, progress, *args)
            except Exception as exc:  # noqa: BLE001 - report any failure to the UI
                store.set_job(project_id, kind, status="error", error=str(exc) or type(exc).__name__)
            else:
                store.set_job(project_id, kind, status="done", progress=1.0, finished=time.time())

        executor.submit(run)

    # ------------------------------------------------------------------ jobs

    def preview_job(project_id: str, progress) -> None:
        meta = store.get(project_id)
        directory = store.project_dir(project_id)
        media.make_preview(store.source_path(meta), directory / "preview.mp4", meta["duration"], progress)

    def transcribe_job(project_id: str, progress, req: TranscribeRequest) -> None:
        meta = store.get(project_id)
        words, language = stt.transcribe(
            store.source_path(meta), req.model, req.language, req.task, progress
        )
        cues = build_cues(words, max_chars=req.max_chars, max_line=req.max_line)
        with store.update(project_id) as m:
            m["segments"] = cues
            m["language"] = language

    def render_job(project_id: str, progress) -> None:
        meta = store.get(project_id)
        directory = store.project_dir(project_id)
        style = normalize_style(meta.get("style"), config.FONTS)
        ass = to_ass(meta["segments"], style, meta["width"], meta["height"])
        (directory / "render.ass").write_text(ass, encoding="utf-8")
        media.burn_subtitles(
            directory, store.source_path(meta), "render.ass", directory / "render.mp4",
            meta["duration"], progress,
        )

    # ------------------------------------------------------------------- api

    @app.get("/api/config")
    def get_config() -> dict:
        return {
            "models": config.WHISPER_MODELS,
            "default_model": config.DEFAULT_WHISPER_MODEL,
            "fonts": config.FONTS,
            "default_style": normalize_style(None, config.FONTS),
        }

    @app.get("/api/projects")
    def list_projects() -> list[dict]:
        return [public(m) for m in store.list()]

    @app.post("/api/projects", status_code=201)
    async def upload(file: UploadFile = File(...)) -> dict:
        name = Path(file.filename or "video").name
        suffix = Path(name).suffix.lower()[:10] or ".mp4"
        project_id, directory = store.new_project_dir()
        source = directory / f"source{suffix}"
        size = 0
        try:
            with source.open("wb") as out:
                while chunk := await file.read(UPLOAD_CHUNK):
                    size += len(chunk)
                    if size > config.MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "Файл слишком большой")
                    out.write(chunk)
            info = media.probe(source)
        except media.MediaError as exc:
            _remove_dir(directory)
            raise HTTPException(400, str(exc))
        except BaseException:
            _remove_dir(directory)
            raise

        meta = store.create(
            project_id,
            {"name": name, "source": source.name, "size": size,
             "style": normalize_style(None, config.FONTS), **info},
        )
        if media.needs_preview(source, info):
            start_job(project_id, "preview", preview_job)
            meta = store.get(project_id)
        return public(meta)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        return public(get_meta(project_id))

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: str) -> None:
        get_meta(project_id)
        store.delete(project_id)

    @app.get("/api/projects/{project_id}/media")
    def get_media(project_id: str) -> FileResponse:
        meta = get_meta(project_id)
        if meta["jobs"].get("preview", {}).get("status") in ("queued", "running"):
            raise HTTPException(409, "Видео ещё подготавливается")
        return FileResponse(store.playable_path(meta))

    @app.post("/api/projects/{project_id}/transcribe", status_code=202)
    def transcribe(project_id: str, req: TranscribeRequest) -> dict:
        meta = get_meta(project_id)
        if not meta.get("has_audio"):
            raise HTTPException(400, "В видео нет звуковой дорожки")
        if req.model not in config.WHISPER_MODELS:
            raise HTTPException(400, "Неизвестная модель")
        start_job(project_id, "transcribe", transcribe_job, req)
        return public(get_meta(project_id))

    @app.put("/api/projects/{project_id}/segments")
    def save_segments(project_id: str, body: SegmentsUpdate) -> dict:
        get_meta(project_id)
        segments = normalize_segments(s.model_dump() for s in body.segments)
        with store.update(project_id) as meta:
            meta["segments"] = segments
        return public(meta)

    @app.put("/api/projects/{project_id}/style")
    async def save_style(project_id: str, request: Request) -> dict:
        get_meta(project_id)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "Ожидается объект стиля")
        try:
            style = normalize_style(body, config.FONTS)
        except (TypeError, ValueError):
            raise HTTPException(422, "Некорректный стиль")
        with store.update(project_id) as meta:
            meta["style"] = style
        return public(meta)

    @app.post("/api/projects/{project_id}/import")
    async def import_subtitles(project_id: str, file: UploadFile = File(...)) -> dict:
        get_meta(project_id)
        raw = await file.read(10 * 1024 * 1024)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1251", errors="replace")
        segments = parse_subtitles(text)
        if not segments:
            raise HTTPException(400, "В файле не найдено субтитров (поддерживаются SRT и VTT)")
        with store.update(project_id) as meta:
            meta["segments"] = segments
        return public(meta)

    @app.get("/api/projects/{project_id}/subtitles.{fmt}")
    def export_subtitles(project_id: str, fmt: Literal["srt", "vtt", "ass"]) -> PlainTextResponse:
        meta = get_meta(project_id)
        if fmt == "srt":
            body, mime = to_srt(meta["segments"]), "application/x-subrip"
        elif fmt == "vtt":
            body, mime = to_vtt(meta["segments"]), "text/vtt"
        else:
            style = normalize_style(meta.get("style"), config.FONTS)
            body, mime = to_ass(meta["segments"], style, meta["width"], meta["height"]), "text/x-ssa"
        filename = f"{Path(meta['name']).stem}.{fmt}"
        return PlainTextResponse(
            body,
            media_type=f"{mime}; charset=utf-8",
            headers={"Content-Disposition": _attachment(filename)},
        )

    @app.post("/api/projects/{project_id}/render", status_code=202)
    def render(project_id: str) -> dict:
        meta = get_meta(project_id)
        if not any(s["text"].strip() for s in meta["segments"]):
            raise HTTPException(400, "Нет субтитров для вшивания")
        start_job(project_id, "render", render_job)
        return public(get_meta(project_id))

    @app.get("/api/projects/{project_id}/render.mp4")
    def download_render(project_id: str) -> FileResponse:
        meta = get_meta(project_id)
        path = store.project_dir(project_id) / "render.mp4"
        if meta["jobs"].get("render", {}).get("status") != "done" or not path.exists():
            raise HTTPException(404, "Видео ещё не отрендерено")
        return FileResponse(path, media_type="video/mp4",
                            filename=f"{Path(meta['name']).stem}_subtitles.mp4")

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def _remove_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _attachment(filename: str) -> str:
    ascii_name = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"

