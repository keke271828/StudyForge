"""Optional live exercise and grading smoke test using temporary data."""

import asyncio
import os
import tempfile

os.environ["STUDYFORGE_DATA_DIR"] = tempfile.mkdtemp(prefix="studyforge-exercises-")

from studyforge.ai import DeepSeekClient
from studyforge.db import create_project
from studyforge.exercises import generate_set, grade_feynman, grade_submission, public_set


async def main():
    project = create_project("Physics practice smoke")
    client = DeepSeekClient()
    digest = "[physics_notes.txt｜page 1] Newton's second law: F = m a. Mass is measured in kg, acceleration in m/s^2, and force in N. For constant acceleration a, v = v0 + at. Assume inertial reference frame and negligible air resistance."
    set_id, reports = await generate_set(client, project["id"], [], digest, "牛顿第二定律", 1)
    item = public_set(set_id)
    assert item and "solutions" not in item
    print("Generated questions:", len(item["questions"]), "reviews:", len(reports), flush=True)
    grade = await grade_submission(client, set_id, ["I do not know." for _ in item["questions"]])
    print("Grade:", grade["score"], "Feynman required:", grade["requires_feynman"], flush=True)
    assert "solutions" in public_set(set_id, reveal=True)
    if grade["requires_feynman"]:
        explanation = ("牛顿第二定律描述惯性参考系中合外力与加速度的关系：F=ma。质量 m 的单位是 kg，"
                       "加速度 a 的单位是 m/s²，因此力的单位是 N。若合外力恒定，a=F/m 为常数，速度随时间按 v=v0+at 变化。"
                       "例如一个质量 2 kg 的物体受 6 N 合外力，忽略阻力时加速度为 3 m/s²。这个结论依赖惯性系，"
                       "实际问题还需要考虑摩擦、阻力和合外力的方向。")
        result = await grade_feynman(client, set_id, explanation)
        print("Feynman:", result["score"], "passed:", result["passed"], flush=True)
    print("Temporary output:", os.environ["STUDYFORGE_DATA_DIR"])


if __name__ == "__main__":
    asyncio.run(main())
