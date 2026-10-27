from urllib.parse import unquote

from fastapi.testclient import TestClient

from studyforge import server
from studyforge.config import artifacts_dir
from studyforge.db import create_project, execute, j, now, one, uid


def artifact(project, title='旧名称', fmt='docx', timestamp=None):
    path = artifacts_dir() / (uid() + '.' + fmt)
    path.write_bytes(b'unchanged document bytes')
    item = server.add_artifact(project['id'], [], 'explanation', fmt, title, path)
    if timestamp:
        execute('UPDATE artifacts SET created_at=? WHERE id=?', (timestamp, item['id']))
    return item, path


def test_rename_updates_listing_and_actual_download_but_preserves_content():
    project = create_project('学习项目')
    item, path = artifact(project)
    client = TestClient(server.app)
    response = client.put('/api/artifacts/' + item['id'], json={'name': '哲学概念对照.docx'})
    assert response.status_code == 200 and response.json()['download_filename'] == '哲学概念对照.docx'
    listed = client.get(f"/api/projects/{project['id']}/artifacts").json()[0]
    assert listed['title'] == '哲学概念对照' and listed['download_filename'] == '哲学概念对照.docx'
    downloaded = client.get(item['download_url'])
    assert '哲学概念对照.docx' in unquote(downloaded.headers['content-disposition'])
    assert downloaded.content == path.read_bytes() == b'unchanged document bytes'
    assert client.put('/api/artifacts/' + item['id'], json={'name': '...  '}).status_code == 400


def test_all_sort_options_are_deterministic_and_invalid_order_is_rejected():
    project = create_project('学习项目')
    older, _ = artifact(project, 'Alpha', 'pdf', '2026-01-01T00:00:00+00:00')
    newer, _ = artifact(project, 'Beta', 'docx', '2026-02-01T00:00:00+00:00')
    client = TestClient(server.app)
    base = f"/api/projects/{project['id']}/artifacts"
    for sort, first in [('newest', newer), ('oldest', older), ('name', older), ('format', newer)]:
        assert client.get(base, params={'sort': sort}).json()[0]['id'] == first['id']
    assert client.get(base, params={'sort': 'name; DELETE FROM artifacts'}).status_code == 400
    assert one('SELECT COUNT(*) AS n FROM artifacts')['n'] == 2


def test_delete_removes_only_owned_artifact_and_keeps_shared_or_external_files(tmp_path):
    project = create_project('学习项目')
    item, path = artifact(project)
    client = TestClient(server.app)
    assert client.delete('/api/artifacts/' + item['id']).status_code == 200
    assert not path.exists() and client.get(item['download_url']).status_code == 404
    outside = tmp_path / 'original.pdf'
    outside.write_bytes(b'original source')
    external = server.add_artifact(project['id'], [], 'external', 'pdf', '外部记录', outside)
    assert client.delete('/api/artifacts/' + external['id']).status_code == 200
    assert outside.read_bytes() == b'original source'
    shared, shared_path = artifact(project)
    second = server.add_artifact(project['id'], [], 'external', 'docx', '另一成果', shared_path)
    assert client.delete('/api/artifacts/' + shared['id']).status_code == 200 and shared_path.exists()
    assert client.get(second['download_url']).status_code == 200
