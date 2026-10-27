"""Create isolated new and legacy artifacts for the desktop download check."""
import json
import os
import tempfile
from pathlib import Path

from docx import Document

from studyforge.config import artifacts_dir
from studyforge.db import create_job, create_project, execute, j, now, uid, update_job
from studyforge.server import add_artifact


def main():
    root = Path(tempfile.mkdtemp(prefix='download-smoke-', dir=Path(__file__).resolve().parents[1] / 'build'))
    os.environ['STUDYFORGE_DATA_DIR'] = str(root / 'data')
    project = create_project('下载文件命名自检')
    source_id = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (source_id, project['id'], '社会制度导论.pdf', '.pdf', 'fixture.pdf', '[]', 'ready', None, now()))
    artifact_paths = {}
    for kind, title in [('explanation', '规训权力·AI 讲解'), ('exercise', '配套习题（无答案）')]:
        path = artifacts_dir() / (uid() + '.docx')
        document = Document()
        document.add_paragraph('下载自检：中文名称与文档内容必须完整保留。')
        document.save(path)
        if kind == 'explanation':
            handoff = {'mode': 'mentor_transfer', 'status': 'completed', 'mentor': {'provider': 'codex', 'model': 'tutor-model'},
                       'packet': {'learning_goal': '理解规训权力', 'instructions': [{'instruction': '用概念对照表讲解',
                         'evidence': [{'message_id': 'student', 'quote': '用概念对照表讲解<script>alert(1)</script>'}]}],
                         'understanding': [{'topic': '规训', 'status': 'needs_support', 'observation': '需要解释概念',
                           'teaching_action': '先讲定义与例子', 'evidence': [{'message_id': 'student', 'quote': '这个概念是什么？'}]}],
                         'teaching_strategy': ['解释术语并标注提出者'], 'unresolved_questions': []}}
            artifact = add_artifact(project['id'], [source_id], kind, 'docx', title, path, {'mentor_handoff': handoff})
            artifact_paths[artifact['id']] = str(path)
        else:
            artifact_id = uid()
            execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)',
                    (artifact_id, project['id'], j([source_id]), kind, 'docx', str(path), title, '{}', now()))
            artifact_paths[artifact_id] = str(path)
    pause_job = create_job(project['id'], 'generate', {'project_id': project['id'], 'source_ids': [source_id],
                            'model': 'ui-fixture', 'generation_quality': 'custom'})
    update_job(pause_job, 'queued', 35, {'stage': '界面暂停继续自检'})
    (root / 'fixture.json').write_text(json.dumps({'project_id': project['id'], 'artifact_paths': artifact_paths,
                                                'pause_job': pause_job}), encoding='utf-8')
    print(root)


if __name__ == '__main__':
    main()
