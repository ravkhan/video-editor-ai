"""Projects stored on disk: one directory per uploaded video with a meta.json."""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class NotFound(Exception):
    pass


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._mark_interrupted_jobs()

    # ------------------------------------------------------------------ paths

    def project_dir(self, project_id: str) -> Path:
        if not _ID_RE.match(project_id):
            raise NotFound(project_id)
        path = self.root / project_id
        if not (path / "meta.json").exists():
            raise NotFound(project_id)
        return path

    def source_path(self, meta: dict) -> Path:
        return self.root / meta["id"] / meta["source"]

    def playable_path(self, meta: dict) -> Path:
        directory = self.root / meta["id"]
        preview = directory / "preview.mp4"
        return preview if preview.exists() else directory / meta["source"]

    # --------------------------------------------------------------- metadata

    def new_project_dir(self) -> tuple[str, Path]:
        project_id = uuid.uuid4().hex
        path = self.root / project_id
        path.mkdir()
        return project_id, path

    def create(self, project_id: str, meta: dict) -> dict:
        meta = {"id": project_id, "created": time.time(), "segments": [], "jobs": {}, **meta}
        self._write(project_id, meta)
        return meta

    def get(self, project_id: str) -> dict:
        path = self.project_dir(project_id) / "meta.json"
        with self._lock:
            return json.loads(path.read_text(encoding="utf-8"))

    @contextmanager
    def update(self, project_id: str) -> Iterator[dict]:
        """Read-modify-write a project's metadata atomically."""
        with self._lock:
            meta = self.get(project_id)
            yield meta
            meta["updated"] = time.time()
            self._write(project_id, meta)

    def set_job(self, project_id: str, kind: str, **fields) -> None:
        try:
            with self.update(project_id) as meta:
                job = meta["jobs"].setdefault(kind, {})
                job.update(fields)
        except NotFound:
            pass  # project deleted while the job was running

    def list(self) -> list[dict]:
        projects = []
        for path in self.root.iterdir():
            if (path / "meta.json").exists():
                try:
                    projects.append(self.get(path.name))
                except (NotFound, json.JSONDecodeError):
                    continue
        projects.sort(key=lambda m: m.get("created", 0), reverse=True)
        return projects

    def delete(self, project_id: str) -> None:
        path = self.project_dir(project_id)
        with self._lock:
            shutil.rmtree(path)

    def _write(self, project_id: str, meta: dict) -> None:
        path = self.root / project_id / "meta.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def _mark_interrupted_jobs(self) -> None:
        """Jobs that were running when the server stopped can never finish."""
        for meta in self.list():
            if any(j.get("status") in ("queued", "running") for j in meta.get("jobs", {}).values()):
                with self.update(meta["id"]) as m:
                    for job in m["jobs"].values():
                        if job.get("status") in ("queued", "running"):
                            job.update(status="error", error="Прервано перезапуском сервера")
