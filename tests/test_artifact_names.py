import io
import re
from urllib.parse import unquote

import pytest
from docx import Document
from fastapi.testclient import TestClient

from studyforge import server
from studyforge.artifact_names import download_filename, explanation_title
from studyforge.config import artifacts_dir
from studyforge.db import create_project, execute, j, now, one, uid
from studyforge.exporters import export_document


def decoded_name(response):
    header = response.headers['content-disposition']
    return unquote(header.split("filename*=utf-8''", 1)[1]) if 'filename*=' in header else header.split('filename=', 1)[1].strip('"')


def source(project):
    source_id = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (source_id, project['id'], '社会制度导论.pdf', '.pdf', 'fixture.pdf', '[]', 'ready', None, now()))
    return source_id


def test_explanation_uses_its_actual_topic_without_calling_a_model():
    document = '> # 原文中的另一标题\n\n```python\n# 代码内的标题\n```\n\n# **规训权力与日常制度**\n正文。'
    assert explanation_title(document, '72abc.pdf') == '规训权力与日常制度·AI 讲解'
    assert explanation_title('只有正文。', '社会制度导论.pdf') == '社会制度导论·AI 讲解'


def test_download_header_and_list_use_readable_chinese_name_and_preserve_docx():
    project = create_project('社会科学学习')
    path = export_document('# 规训权力\n实际文档内容。', 'docx', '规训权力', uid()+'.docx')
    artifact = server.add_artifact(project['id'], [], 'explanation', 'docx', '规训权力·AI 讲解', path)
    client = TestClient(server.app)
    response = client.get(artifact['download_url'])
    assert response.status_code == 200
    name = decoded_name(response)
    assert re.fullmatch(r'规训权力_AI讲解_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.docx', name)
    assert path.stem not in name
    listed = client.get(f"/api/projects/{project['id']}/artifacts").json()[0]
    assert artifact['download_filename'] == listed['download_filename'] == name
    assert any('实际文档内容' in p.text for p in Document(io.BytesIO(response.content)).paragraphs)


@pytest.mark.parametrize('kind,title,expected', [
    ('original', '视频原文档', '视频原文档'),
    ('exercise', '配套习题（无答案）', '配套习题'),
    ('exercise', '进阶习题（无答案）', '进阶习题'),
    ('solutions', '习题与解析', '习题与解析'),
])
def test_legacy_files_get_source_topic_in_download_name(kind, title, expected):
    project = create_project('读书项目')
    source_id = source(project)
    artifact_id = uid()
    path = artifacts_dir() / (uid()+'.docx')
    path.write_bytes(b'legacy content')
    execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)',
            (artifact_id, project['id'], j([source_id]), kind, 'docx', str(path), title, '{}', now()))
    response = TestClient(server.app).get(f'/api/artifacts/{artifact_id}/download')
    assert response.status_code == 200
    name = decoded_name(response)
    assert name.startswith('社会制度导论_'+expected) and name.endswith('.docx')
    assert '.pdf' not in name and artifact_id not in name and path.stem not in name
    assert response.content == b'legacy content'


def test_saved_name_stays_readable_after_original_source_is_deleted():
    project = create_project('学习项目')
    source_id = source(project)
    path = artifacts_dir() / (uid()+'.docx')
    path.write_bytes(b'fixture')
    artifact = server.add_artifact(project['id'], [source_id], 'exercise', 'docx', '配套习题（无答案）', path)
    execute('DELETE FROM sources WHERE id=?', (source_id,))
    name = decoded_name(TestClient(server.app).get(artifact['download_url']))
    assert name == artifact['download_filename'] and name.startswith('社会制度导论_')


@pytest.mark.parametrize('fmt,extension', [('word','docx'), ('ppt','pptx'), ('anki','apkg'), ('mindmap','mm')])
def test_compatible_format_aliases_have_real_file_extensions(fmt, extension):
    name = download_filename('学习笔记', 'external', fmt, 'coded.'+fmt, '2026-10-02T07:00:00+00:00')
    assert name.endswith('.'+extension)


def test_invalid_windows_characters_and_header_controls_are_removed():
    name = download_filename('概念<对照>:A/B\\C?*\r\n"条目"', 'explanation', 'pdf', uid()+'.pdf', '2026-10-02T07:00:00+00:00')
    assert '概念' in name and '条目' in name and name.endswith('.pdf')
    assert not re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
    assert len(name) < 180


def test_old_url_and_uuid_titles_fall_back_to_project_and_versions_are_distinct():
    arguments = ('https://b23.tv/example·AI 讲解', 'explanation', 'pdf', uid()+'.pdf')
    first = download_filename(*arguments, '2026-10-02T07:00:00+00:00', project_name='社会科学学习')
    second = download_filename(*arguments, '2026-10-02T07:00:02+00:00', project_name='社会科学学习')
    assert first.startswith('社会科学学习_AI讲解_') and first != second
    name = download_filename('视频原文档', 'original', 'docx', 'coded.docx', now(),
                             source_names=[uid()+'.mp4'], project_name='视频学习')
    assert name.startswith('视频学习_视频原文档_')
