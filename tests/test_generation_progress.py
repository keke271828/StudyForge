import asyncio

from fastapi.testclient import TestClient

from studyforge.ai import clear_source_digest_cache, source_digest
from studyforge.db import create_job, create_project, update_job
from studyforge.server import app


class FakeClient:
    def __init__(self):
        self.calls = 0

    async def complete(self, system, user):
        self.calls += 1
        return "已整理"


def test_short_source_uses_full_original_without_extra_model_round_trip():
    clear_source_digest_cache()
    client = FakeClient()
    source = {"id": "short", "name": "力学.txt", "segments": [
        {"locator": "第 1 段", "text": "力等于质量乘以加速度。", "meta": {}}]}
    digest, chunks = asyncio.run(source_digest(client, [source]))
    assert "力等于质量乘以加速度" in digest
    assert "力学.txt｜第 1 段" in digest
    assert chunks and client.calls == 0


def test_long_source_digest_is_reused_for_same_material():
    clear_source_digest_cache()
    client = FakeClient()
    source = {"id": "long", "name": "长资料.txt", "segments": [
        {"locator": "第 1 段", "text": "物理推导。" * 4000, "meta": {}}]}
    first, chunks = asyncio.run(source_digest(client, [source]))
    assert len(chunks) > 1 and client.calls == 0
    assert first.count('物理推导。') == 4000
    second, _ = asyncio.run(source_digest(client, [source]))
    assert second == first and client.calls == 0


def test_long_source_is_not_sent_to_a_summary_model():
    class SlowClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.max_active = 0

        async def complete(self, system, user):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(.02)
            self.active -= 1
            return await super().complete(system, user)

    clear_source_digest_cache()
    client = SlowClient()
    source = {"id": "parallel", "name": "长资料.txt", "segments": [
        {"locator": "第 1 段", "text": "物理定律。" * 9000, "meta": {}}]}
    original, _ = asyncio.run(source_digest(client, [source]))
    assert client.calls == 0
    assert original.count('物理定律。') == 9000


def test_image_segments_are_analyzed_in_parallel_without_losing_locators(tmp_path):
    class VisionClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.max_active = 0
            self.group_ready = asyncio.Event()

        async def analyze_image(self, path, locator, original):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active == 3: self.group_ready.set()
            await asyncio.wait_for(self.group_ready.wait(), 3)
            self.active -= 1
            return f"识别到 {locator}"

    clear_source_digest_cache()
    segments = []
    for index in range(5):
        image = tmp_path / f"frame-{index}.png"
        image.write_bytes(b"image")
        segments.append({"locator": f"第 {index} 帧", "text": "板书", "meta": {"image_path": str(image)}})
    client = VisionClient()
    digest, _ = asyncio.run(source_digest(client, [{"id": "images", "name": "视频", "segments": segments}]))
    assert client.max_active == 3
    assert all(f"视频｜第 {index} 帧" in digest for index in range(5))


def test_job_list_exposes_live_generation_stage():
    project = create_project("进度")
    job_id = create_job(project["id"], "generate", {})
    update_job(job_id, "running", 59, {"stage": "事实与推导审查"})
    jobs = TestClient(app).get(f"/api/projects/{project['id']}/jobs").json()
    assert jobs[0]["stage"] == "事实与推导审查"
    assert jobs[0]["progress"] == 59
