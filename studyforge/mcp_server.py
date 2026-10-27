from __future__ import annotations

import json
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .coding import grade_code
from .config import artifacts_dir
from .db import many, one, uid, unj
from .exercises import grade_submission, public_set
from .materials import read_original_sources
from .parsers import decode_text
from .navigation import projects, require_project
from .server import add_artifact, assessment_client

mcp = FastMCP("StudyForge", instructions=(
    "StudyForge 提供本机学习资料与作业。先列出项目和资料，再按 ID 读取。"
    "严禁在学生提交前请求或披露习题答案。提交工具会回传批改结果。"
    "读取资料时保留来源定位；写入成果只使用明确指定的项目。"
))


async def grading_client(provider=None, model=None, reasoning_effort=None):
    """Use the AI service selected in StudyForge for MCP submissions too."""
    return await assessment_client(provider, model, reasoning_effort)


@mcp.tool()
def list_projects() -> list[dict]:
    """列出本机学习项目。"""
    return [{key: row[key] for key in ('id', 'name', 'created_at')} for row in projects()]


@mcp.tool()
def list_sources(project_id: str) -> list[dict]:
    """列出指定项目的资料与解析状态。"""
    require_project(project_id)
    return many("SELECT id,name,kind,status,error,category_id FROM sources WHERE project_id=?", (project_id,))


@mcp.tool()
def list_categories(project_id: str) -> list[dict]:
    """列出指定项目的资料分类，便于按分类选择资料。"""
    require_project(project_id)
    return many("SELECT id,name FROM source_categories WHERE project_id=? ORDER BY created_at", (project_id,))


@mcp.tool()
def read_source(source_id: str, offset: int = 0, limit: int = 25) -> dict:
    """按段读取所选文件，视频用完整转录与采样帧。read_manifest.content_origin区分已知AI成果与导入资料；读取方式不证明内容正确或已回查所引原文。"""
    if offset < 0 or not 1 <= limit <= 100: raise ValueError('offset 须非负，limit 须为 1 到 100')
    row = one("SELECT * FROM sources WHERE id=?", (source_id,))
    if not row:
        raise ValueError("资料不存在")
    require_project(row['project_id'])
    if row['status'] != 'ready': raise ValueError('资料尚未成功解析，请在软件中完成导入')
    original = read_original_sources([dict(row, segments=unj(row['segments_json'], []))])[0]
    segments = original['segments']
    end = offset + limit
    return {key: row[key] for key in ('id', 'name', 'status')} | {
        'total': len(segments), 'offset': offset, 'segments': segments[offset:end],
        'next_offset': end if end < len(segments) else None, 'read_manifest': original['read_manifest']}


@mcp.tool()
def list_assignments(project_id: str) -> list[dict]:
    """列出项目习题与编程作业；提交前不包含答案。"""
    require_project(project_id)
    rows = many("SELECT id FROM exercise_sets WHERE project_id=? ORDER BY created_at DESC", (project_id,))
    return [public_set(row["id"]) for row in rows]


@mcp.tool()
def read_assignment(assignment_id: str) -> dict:
    """读取题目、起始代码和状态；提交前不包含答案。"""
    require_assignment_project(assignment_id)
    item = public_set(assignment_id)
    if not item:
        raise ValueError("作业不存在")
    return item


@mcp.tool()
async def submit_answers(assignment_id: str, answers: list[str], provider: str | None = None,
                         model: str | None = None, reasoning_effort: str | None = None) -> dict:
    """提交全部非编程题答案并获得严格批改；提交后题目解析可在应用中查看。"""
    require_assignment_project(assignment_id)
    return await grade_submission(await grading_client(provider, model, reasoning_effort), assignment_id, answers)


@mcp.tool()
async def submit_python_file(assignment_id: str, absolute_path: str, provider: str | None = None,
                             model: str | None = None, reasoning_effort: str | None = None) -> dict:
    """提交本机 Python 作业文件，运行隔离测试并返回批改。"""
    require_assignment_project(assignment_id)
    path = Path(absolute_path).resolve()
    if path.suffix.lower() != ".py" or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("请提供不超过 2 MB 的本机 .py 文件")
    return await grade_code(await grading_client(provider, model, reasoning_effort), assignment_id, decode_text(path.read_bytes())[0])


@mcp.tool()
async def submit_code_file(assignment_id: str, absolute_path: str, provider: str | None = None,
                           model: str | None = None, reasoning_effort: str | None = None) -> dict:
    """提交 Python、JavaScript、TypeScript、C++、MATLAB 或 Wolfram Language 作业文件。"""
    require_assignment_project(assignment_id)
    assignment = public_set(assignment_id)
    if not assignment or not assignment["questions"]:
        raise ValueError("编程作业不存在")
    language = assignment["questions"][0].get("language")
    extensions = {"python": ".py", "javascript": ".js", "typescript": ".ts",
                  "cpp": ".cpp", "matlab": ".m", "wolfram": ".wl"}
    path = Path(absolute_path).resolve()
    if language not in extensions or path.suffix.lower() != extensions[language] or not path.is_file():
        raise ValueError("文件语言与作业要求不一致")
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("代码文件最大 2 MB")
    return await grade_code(await grading_client(provider, model, reasoning_effort), assignment_id, decode_text(path.read_bytes())[0])


@mcp.tool()
def attach_artifact(project_id: str, absolute_path: str, title: str) -> dict:
    """将 Codex 或 DeepSeek Harness 生成的本机文件回传至学习项目。"""
    require_project(project_id)
    source = Path(absolute_path).resolve()
    if not source.is_file() or source.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("仅接受不超过 100 MB 的现有文件")
    target = artifacts_dir() / f"{uid()}{source.suffix.lower()}"
    shutil.copyfile(source, target)
    return add_artifact(project_id, [], "external", source.suffix.lstrip(".") or "file", title[:120], target)


def require_assignment_project(assignment_id):
    row = one('SELECT project_id FROM exercise_sets WHERE id=?', (assignment_id,))
    if not row: raise ValueError('作业不存在')
    return require_project(row['project_id'])


@mcp.tool()
def get_learning_profile() -> list[dict]:
    """读取有效跨项目评估参考与自评；分数不代表经校准的能力，移出画像的记录不参与。"""
    from .learning_profile import effective_profile
    return effective_profile()


if __name__ == "__main__":
    mcp.run(transport="stdio")
