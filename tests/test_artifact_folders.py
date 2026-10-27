from fastapi.testclient import TestClient

from studyforge import server
from studyforge.config import artifacts_dir
from studyforge.db import create_job, create_project, execute, one, update_job


def test_project_folders_count_files_and_tasks_without_join_multiplication_or_contents():
    first, second, empty = [create_project(name) for name in ['哲学', '编程', '空项目']]
    for project, titles in [(first, ['内部文件A', '内部文件B']), (second, ['另一个项目的文件'])]:
        for index, title in enumerate(titles):
            path = artifacts_dir() / (project['id']+str(index)+'.txt')
            path.write_text('不能在文件夹目录中泄露的内容', encoding='utf-8')
            server.add_artifact(project['id'], [], 'explanation', 'txt', title, path)
    for status in ['queued', 'running', 'pausing', 'paused', 'completed', 'failed']:
        job = create_job(first['id'], 'generate', {})
        update_job(job, status, 10)
    api = TestClient(server.app)
    rows = api.get('/api/artifact-folders').json()
    folders = {row['id']: row for row in rows}
    assert folders[first['id']]['artifact_count'] == 2 and folders[first['id']]['pending_count'] == 4
    assert folders[second['id']]['artifact_count'] == 1 and folders[second['id']]['pending_count'] == 0
    assert folders[empty['id']]['artifact_count'] == folders[empty['id']]['pending_count'] == 0
    assert folders[empty['id']]['latest_artifact_at'] is None
    assert '内部文件' not in str(rows) and '不能在文件夹目录' not in str(rows)
    assert len(api.get('/api/projects/'+first['id']+'/artifacts').json()) == 2
    assert len(api.get('/api/projects/'+second['id']+'/artifacts').json()) == 1
    assert api.get('/api/projects/'+empty['id']+'/artifacts').json() == []


def test_folder_counts_follow_rename_delete_and_new_files_without_moving_artifacts():
    project, other = create_project('本项目'), create_project('其他项目')
    path = artifacts_dir() / 'result.txt'; path.write_text('成果', encoding='utf-8')
    item = server.add_artifact(project['id'], [], 'explanation', 'txt', '原名', path)
    api = TestClient(server.app)
    def folders(): return {row['id']:row for row in api.get('/api/artifact-folders').json()}
    assert folders()[project['id']]['artifact_count'] == 1
    assert api.put('/api/artifacts/'+item['id'], json={'name':'新名称'}).status_code == 200
    assert folders()[project['id']]['artifact_count'] == 1
    assert one('SELECT project_id FROM artifacts WHERE id=?', (item['id'],))['project_id'] == project['id']
    assert api.delete('/api/artifacts/'+item['id']).status_code == 200
    assert folders()[project['id']]['artifact_count'] == folders()[other['id']]['artifact_count'] == 0
    assert api.get('/api/projects/'+other['id']+'/artifacts').json() == []
