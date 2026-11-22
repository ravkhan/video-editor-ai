"""API tests with a fake transcriber and real FFmpeg on tiny generated videos."""

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.subtitles import Word

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe(self, path, model, language, task, on_progress):
        self.calls.append((Path(path).name, model, language, task))
        on_progress(0.5)
        text = "Привет это тест. Второе предложение здесь"
        result, t = [], 0.1
        for i, w in enumerate(text.split()):
            result.append(Word(t, t + 0.3, (" " if i else "") + w))
            t += 0.35
        on_progress(1.0)
        return result, "ru"


def make_video(path: Path, ext_args=(), audio=True, size="320x240") -> Path:
    args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=10:duration=3"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"]
    args += ["-pix_fmt", "yuv420p", *ext_args, "-shortest", str(path)]
    subprocess.run(args, check=True)
    return path


@pytest.fixture
def fake():
    return FakeTranscriber()


@pytest.fixture
def client(tmp_path, fake):
    with TestClient(create_app(tmp_path, fake)) as c:
        yield c


def upload(client, path: Path):
    with path.open("rb") as f:
        return client.post("/api/projects", files={"file": (path.name, f, "video/mp4")})


def wait_job(client, project_id, kind, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        project = client.get(f"/api/projects/{project_id}").json()
        job = project["jobs"].get(kind, {})
        if job.get("status") in ("done", "error"):
            return project
        time.sleep(0.1)
    raise AssertionError(f"{kind} job did not finish")


def test_index_and_config(client):
    assert "Video Editor AI" in client.get("/").text
    cfg = client.get("/api/config").json()
    assert "small" in cfg["models"] and cfg["fonts"]


def test_full_flow(client, fake, tmp_path):
    video = make_video(tmp_path / "Мой ролик.mp4", ["-c:v", "libx264", "-c:a", "aac"])
    res = upload(client, video)
    assert res.status_code == 201, res.text
    project = res.json()
    pid = project["id"]
    assert project["width"] == 320 and project["height"] == 240
    assert 2.5 < project["duration"] < 3.5
    assert "preview" not in project["jobs"]  # H.264/AAC mp4 plays directly
    assert "source" not in project

    media = client.get(f"/api/projects/{pid}/media", headers={"Range": "bytes=0-99"})
    assert media.status_code == 206 and len(media.content) == 100

    # transcription
    res = client.post(f"/api/projects/{pid}/transcribe", json={"model": "tiny", "language": "ru"})
    assert res.status_code == 202
    project = wait_job(client, pid, "transcribe")
    assert project["jobs"]["transcribe"]["status"] == "done", project["jobs"]
    assert project["language"] == "ru"
    assert [s["text"] for s in project["segments"]] == ["Привет это тест.", "Второе предложение здесь"]
    assert fake.calls[0][1:] == ("tiny", "ru", "transcribe")

    # editing
    segments = project["segments"]
    segments[0]["text"] = "Привет, это тест!"
    res = client.put(f"/api/projects/{pid}/segments", json={"segments": segments})
    assert res.status_code == 200
    assert res.json()["segments"][0]["text"] == "Привет, это тест!"

    res = client.put(f"/api/projects/{pid}/style", json={"color": "#FFFF00", "size": 60, "box": True})
    assert res.json()["style"]["color"] == "#FFFF00"

    # export
    srt = client.get(f"/api/projects/{pid}/subtitles.srt")
    assert srt.status_code == 200
    assert "Привет, это тест!" in srt.text
    assert "filename*=UTF-8''%D0%9C%D0%BE%D0%B9" in srt.headers["content-disposition"]
    assert client.get(f"/api/projects/{pid}/subtitles.vtt").text.startswith("WEBVTT")
    assert "PlayResX: 320" in client.get(f"/api/projects/{pid}/subtitles.ass").text

    # render
    assert client.get(f"/api/projects/{pid}/render.mp4").status_code == 404
    assert client.post(f"/api/projects/{pid}/render").status_code == 202
    project = wait_job(client, pid, "render")
    assert project["jobs"]["render"]["status"] == "done", project["jobs"]["render"]
    out = client.get(f"/api/projects/{pid}/render.mp4")
    assert out.status_code == 200 and out.headers["content-type"] == "video/mp4"
    rendered = tmp_path / "out.mp4"
    rendered.write_bytes(out.content)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(rendered)],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert probe == ["h264", "aac"]

    # list & delete
    assert [p["id"] for p in client.get("/api/projects").json()] == [pid]
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_non_browser_format_gets_preview(client, tmp_path):
    video = make_video(tmp_path / "clip.avi", ["-c:v", "mpeg4", "-c:a", "mp3"])
    project = upload(client, video).json()
    assert project["jobs"]["preview"]["status"] in ("queued", "running", "done")
    project = wait_job(client, project["id"], "preview")
    assert project["jobs"]["preview"]["status"] == "done", project["jobs"]
    media = client.get(f"/api/projects/{project['id']}/media")
    assert media.headers["content-type"] == "video/mp4"


def test_rejects_non_video(client, tmp_path):
    bad = tmp_path / "notes.mp4"
    bad.write_text("hello")
    res = upload(client, bad)
    assert res.status_code == 400
    assert client.get("/api/projects").json() == []


def test_transcribe_requires_audio(client, tmp_path):
    video = make_video(tmp_path / "silent.mp4", ["-c:v", "libx264"], audio=False)
    pid = upload(client, video).json()["id"]
    assert client.post(f"/api/projects/{pid}/transcribe", json={}).status_code == 400
    assert client.post(f"/api/projects/{pid}/render").status_code == 400  # no subtitles yet


def test_import_srt(client, tmp_path):
    video = make_video(tmp_path / "v.mp4", ["-c:v", "libx264", "-c:a", "aac"])
    pid = upload(client, video).json()["id"]
    srt = "1\n00:00:00,500 --> 00:00:01,500\nПервый\n\n2\n00:00:02,000 --> 00:00:02,900\nВторой\n"
    res = client.post(f"/api/projects/{pid}/import",
                      files={"file": ("subs.srt", srt.encode("cp1251"), "text/plain")})
    assert res.status_code == 200
    assert [s["text"] for s in res.json()["segments"]] == ["Первый", "Второй"]
    bad = client.post(f"/api/projects/{pid}/import", files={"file": ("x.srt", b"nothing", "text/plain")})
    assert bad.status_code == 400


def test_invalid_project_id(client):
    assert client.get("/api/projects/../../etc").status_code == 404
    assert client.get("/api/projects/" + "z" * 32).status_code == 404


def test_rotated_video_dimensions(client, tmp_path):
    src = make_video(tmp_path / "src.mp4", ["-c:v", "libx264", "-c:a", "aac"], size="320x240")
    rotated = tmp_path / "rotated.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-display_rotation", "90", "-i", str(src),
                    "-c", "copy", str(rotated)], check=True)
    project = upload(client, rotated).json()
    assert (project["width"], project["height"]) == (240, 320)
