"""Local video transcription, frame OCR, and original-document smoke test."""

import asyncio
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pyttsx3

os.environ["STUDYFORGE_DATA_DIR"] = tempfile.mkdtemp(prefix="studyforge-video-")

from studyforge.ai import save_settings
from studyforge.db import create_job, create_project, execute, now, one, uid
from studyforge.media import run_ffmpeg
from studyforge.parsers import parse_file
from studyforge.server import _import_job


async def main():
    root = Path(os.environ["STUDYFORGE_DATA_DIR"])
    save_settings({"whisper_model": "tiny"})
    slide = root / "slide.png"
    image = Image.new("RGB", (1280, 720), "white")
    ImageDraw.Draw(image).text((180, 200), "F = m a", fill="black", font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 100))
    image.save(slide)
    voice = root / "voice.wav"
    engine = pyttsx3.init()
    engine.save_to_file("Force equals mass times acceleration.", str(voice))
    engine.runAndWait()
    video = root / "physics.mp4"
    run_ffmpeg("-loop", "1", "-i", str(slide), "-i", str(voice), "-shortest", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", str(video))
    project = create_project("Video smoke")
    source_id = uid()
    execute("INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (source_id, project["id"], "physics.mp4", ".mp4", str(video), "[]", "pending", None, now()))
    job_id = create_job(project["id"], "import", {})
    await _import_job(job_id, source_id, video)
    job = one("SELECT status,error FROM jobs WHERE id=?", (job_id,))
    source = one("SELECT segments_json FROM sources WHERE id=?", (source_id,))
    print(job, source["segments_json"][:500], flush=True)
    assert job["status"] == "completed"
    assert "Force equals" in source["segments_json"]
    assert "F = m" in source["segments_json"]
    original = root / "artifacts" / f"{source_id}-original.docx"
    from docx import Document
    assert len(Document(original).inline_shapes) >= 1
    silent = root / "silent.mp4"
    run_ffmpeg("-loop", "1", "-i", str(slide), "-t", "1", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", str(silent))
    assert any(item["kind"] == "video_frame" for item in parse_file(silent))


if __name__ == "__main__":
    asyncio.run(main())
