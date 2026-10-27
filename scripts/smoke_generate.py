"""Optional live DeepSeek integration smoke test; uses temporary local data."""

import asyncio
import os
import sys
import tempfile
import time

os.environ["STUDYFORGE_DATA_DIR"] = tempfile.mkdtemp(prefix="studyforge-smoke-")

from studyforge.db import create_job, create_project, execute, j, now, one, uid
from studyforge.ai import save_settings
from studyforge.server import GenerateIn, _generate_job
from studyforge.config import files_dir
from studyforge.codex_bridge import bridge
from studyforge import model_catalog


async def main():
    selected_model = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--model=")), None)
    if selected_model:
        save_settings({"codex_generation_model": selected_model})
    project = create_project("Physics smoke")
    source_id = uid()
    segments = [
        {"locator": "page 1", "text": "A mass m on a spring of stiffness k follows m x'' + k x = 0. Angular frequency omega = sqrt(k/m). The general solution is x(t)=A cos(omega t + phi). Energy E = 1/2 m v^2 + 1/2 k x^2 is constant in the ideal model. Units: k is N/m; omega is rad/s. Damping and driving are outside this model.", "kind": "page", "meta": {}},
    ]
    original = files_dir() / 'oscillator.txt'
    original.write_text(segments[0]['text'], encoding='utf-8')
    execute("INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (source_id, project["id"], "oscillator.txt", ".txt", str(original), j(segments), "ready", None, now()))
    selected = model_catalog.recommended_generation((await model_catalog.get_models())['models'])
    selected_level = int(next((arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--level=')), '3'))
    print('Actual generation model:', selected_model or selected['model'], selected['effort'], flush=True)
    payload = GenerateIn(project_id=project["id"], source_ids=[source_id], format="docx",
                         summary_level=selected_level, exercises="--exercises" in sys.argv, provider='codex',
                         model=selected_model or selected['model'], reasoning_effort=selected['effort'])
    job_id = create_job(project["id"], "generate", payload.model_dump())
    started = time.perf_counter()
    await _generate_job(job_id, payload)
    await bridge.close()
    result = one("SELECT status,error,result_json FROM jobs WHERE id=?", (job_id,))
    print(result)
    print("Elapsed seconds:", round(time.perf_counter() - started, 1))
    print("Temporary output:", os.environ["STUDYFORGE_DATA_DIR"])
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
