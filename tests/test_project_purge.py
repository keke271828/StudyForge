import asyncio
import hashlib
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studyforge import conversations, learning_memory as memory, learning_profile, project_purge, server
from studyforge.config import artifacts_dir, data_dir, files_dir, derived_dir
from studyforge.db import connect, create_job, create_project, execute, j, many, now, one, uid, update_mastery


def source(project, path, parts=None):
    identifier = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (identifier, project['id'], path.name, path.suffix, str(path), j(parts or []), 'ready', now()))
    return identifier


def recycle(project):
    response = TestClient(server.app).delete('/api/projects/' + project['id'])
    assert response.status_code == 200, response.text


def test_only_recycled_projects_can_be_purged_and_exact_confirmation_is_required():
    project = create_project('必须确认的项目')
    client = TestClient(server.app)
    url = '/api/recycle-bin/projects/' + project['id']
    assert client.get(url + '/impact').status_code == 404
    assert client.request('DELETE', url, json={'confirmation_name': project['name']}).status_code == 404
    recycle(project)
    for name in ['', None, '错误名称']:
        assert client.request('DELETE', url, json={'confirmation_name': name}).status_code == 400
        assert one('SELECT * FROM projects WHERE id=?', (project['id'],))
    assert client.request('DELETE', url, json={'confirmation_name': project['name']}).json()['deleted']
    assert client.post('/api/projects/' + project['id'] + '/restore').status_code == 404
    assert client.request('DELETE', url, json={'confirmation_name': project['name']}).status_code == 404


def test_purge_cleans_entire_owned_graph_files_and_profile_without_touching_other_project(tmp_path):
    project, other = create_project('被删除的学习'), create_project('继续学习')
    chat = conversations.create(project['id'], 'deepseek')
    foreign = conversations.create(other['id'], 'deepseek')
    original = tmp_path / '用户原文件.txt'; original.write_text('保留原件', encoding='utf-8')
    source(project, original)
    local = files_dir() / (uid() + '.sfvideo'); local.write_text('{}', encoding='utf-8')
    frames = local.with_suffix('.frames'); frames.mkdir(); (frames/'00000.png').write_bytes(b'frame')
    local.with_suffix('.sfvideo.video.json').write_text('{}', encoding='utf-8')
    cache = derived_dir(local, 'frames'); (cache/'frame.png').write_bytes(b'cached')
    source_id = source(project, local, [{'meta': {'image_path': str(cache/'frame.png')}}])
    document = artifacts_dir()/'说明.txt'; document.write_text('本项目成果', encoding='utf-8')
    artifact = server.add_artifact(project['id'], [source_id], 'explanation', 'txt', '成果', document)
    shared = files_dir()/'共享.txt'; shared.write_text('仍被引用', encoding='utf-8')
    source(project, shared); foreign_source = source(other, shared)
    message = uid(); execute('INSERT INTO messages VALUES (?,?,?,?,?)', (message, chat['id'], 'user', '高斯定律是什么意思', now()))
    job = create_job(project['id'], 'generate', {'conversation_id': chat['id']})
    execute('INSERT INTO generation_steps VALUES (?,?,?,?)', (job, 'lesson', '原讲解', now()))
    execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)', (job, chat['id'], message))
    execute('INSERT INTO agent_dialogue_state VALUES (?,?,?,?,?)', (chat['id'], 0, '[]', now(), 1))
    scope = 'chat:' + project['id'] + ':' + chat['id']
    folder = data_dir()/'agent-workspace'/hashlib.sha256(scope.encode()).hexdigest()[:32]
    folder.mkdir(parents=True); (folder/'笔记.txt').write_text('对话工作文件', encoding='utf-8')
    execute('INSERT INTO agent_dialogue_scopes VALUES (?,?,?)', (chat['id'], project['id'], scope))
    private = data_dir()/'assessment-workspace'/uid(); private.mkdir(parents=True); (private/'解答.txt').write_text('私有解答', encoding='utf-8')
    execute('INSERT INTO agent_workspaces VALUES (?,?,?,?)', ('private:test', project['id'], str(private), now()))
    worksheet = uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)', (worksheet, project['id'], '[]', '高斯定律', '[]', '[]', 1, 'assigned', now()))
    execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)', (uid(), worksheet, '{}', '{}', 60, '{}', now()))
    execute('INSERT INTO practice_options VALUES (?,?,?)', (worksheet, 'strict', now()))
    execute('INSERT INTO practice_hints VALUES (?,?,?,?,?)', (worksheet, 0, 'hint', 1, now()))
    execute('INSERT INTO review_items VALUES (?,?,?,?,?,?,?,?,?)', (uid(), worksheet, 0, 1, now(), now(), worksheet, now(), now()))
    execute('INSERT INTO review_sessions VALUES (?,?,?,?)', (worksheet, '[]', now(), None))
    execute('INSERT INTO agent_approvals VALUES (?,?,?,?,?,?,?,?,?,?,?)', (uid(), project['id'], chat['id'], job, 'sf_write_text', 'signature', '{}', 'denied', None, now(), now()))
    execute('INSERT INTO desktop_notices(notice_key,category,title,body,target_json,created_at) VALUES (?,?,?,?,?,?)', ('project:test', 'artifact', '已完成', '内容', j({'project_id': project['id']}), now()))
    update_mastery('高斯定律', quiz=20)
    memory.assessment_record('quiz:deleted', '高斯定律', '做题', 20, '本项目答案', '错因', project['id'])
    update_mastery('高斯定律', quiz=80)
    memory.assessment_record('quiz:kept', '高斯定律', '做题', 80, '另一项目答案', '正确', other['id'])
    memory.assessment_record('quiz:gone', '仅本项目', '做题', 30, '答案', '', project['id'])
    update_mastery('仅本项目', quiz=30)
    memory.assessment_record('self:global', '个人自评', '自评', 70, '学生自评', '')
    before_revision = learning_profile.profile_revision()
    recycle(project)
    client = TestClient(server.app)
    impact = client.get(f"/api/recycle-bin/projects/{project['id']}/impact").json()
    assert impact['conversation_count'] == 1 and impact['message_count'] == 1
    assert impact['file_count'] >= 6 and impact['preserved_external_files'] >= 1
    result = client.request('DELETE', f"/api/recycle-bin/projects/{project['id']}", json={'confirmation_name': project['name']})
    assert result.status_code == 200, result.text
    assert result.json()['preserved_shared_paths'] and not result.json()['cleanup_pending']
    assert original.read_text(encoding='utf-8') == '保留原件' and shared.exists()
    assert all(not item.exists() for item in (local, frames, cache, document, folder, private))
    assert many('SELECT * FROM projects') == [other]
    assert one('SELECT * FROM conversations WHERE id=?', (foreign['id'],))
    assert one('SELECT * FROM sources WHERE id=?', (foreign_source,))
    for table in ('jobs', 'generation_steps', 'messages', 'exercise_sets', 'submissions', 'review_items',
                  'agent_workspaces', 'agent_dialogue_state', 'agent_approvals', 'desktop_notices', 'artifact_sources'):
        assert many('SELECT * FROM ' + table) == [], table
    assert client.get(f"/api/artifacts/{artifact['id']}/download").status_code == 404
    assert client.get('/api/recycle-bin/projects').json() == []
    rows = {row['topic']: row for row in learning_profile.effective_profile()}
    assert rows['高斯定律']['score'] == 80 and '仅本项目' not in rows
    assert rows['个人自评']['self_rating'] == 70
    assert learning_profile.profile_revision() != before_revision
    with connect() as database: assert database.execute('PRAGMA foreign_key_check').fetchall() == []


def test_file_move_failure_rolls_back_records_and_prior_moves(monkeypatch):
    project = create_project('事务回滚')
    first, second = files_dir()/'a.txt', files_dir()/'b.txt'
    first.write_text('a'); second.write_text('b'); source(project, first); source(project, second)
    recycle(project)
    replace = Path.replace
    def fail_second(path, target):
        if path == second: raise PermissionError('文件被占用')
        return replace(path, target)
    monkeypatch.setattr(Path, 'replace', fail_second)
    with pytest.raises(PermissionError): project_purge.purge(project['id'], project['name'])
    assert first.read_text() == 'a' and second.read_text() == 'b'
    assert len(many('SELECT * FROM sources')) == 2 and one('SELECT * FROM removed_projects')
    assert list((data_dir()/'tmp').glob('project-purge-*')) == []


def test_shared_video_records_keep_companion_frames_and_derived_cache():
    project, other = create_project('删除'), create_project('保留')
    path = files_dir()/'shared.sfvideo'; path.write_text('{}')
    frames = path.with_suffix('.frames'); frames.mkdir(); (frames/'frame.png').write_bytes(b'frame')
    cache = derived_dir(path, 'frames'); (cache/'frame.png').write_bytes(b'cache')
    source(project, path); source(other, path)
    recycle(project)
    project_purge.purge(project['id'], project['name'])
    assert path.exists() and frames.exists() and cache.exists()


def test_other_project_fk_references_block_purge_without_cascading():
    project, other = create_project('甲'), create_project('乙')
    job = create_job(project['id'], 'test', {})
    execute('INSERT INTO agent_tool_events VALUES (?,?,?,?,?,?,?,?,?)', (uid(), other['id'], None, job, 'test', 'completed', '{}', now(), now()))
    recycle(project)
    with pytest.raises(project_purge.PurgeConflict): project_purge.purge(project['id'], project['name'])
    assert len(many('SELECT * FROM projects')) == 2 and one('SELECT * FROM agent_tool_events')


def test_background_response_cannot_resurrect_permanently_deleted_project():
    project = create_project('后台删除')
    memory.record_event('chat:deleted', 'chat', {'student_text':'高斯定律是什么，我不理解高斯定律'}, project_id=project['id'], provider='deepseek')
    class Client:
        async def complete(self, *args, **kwargs):
            execute('INSERT INTO removed_projects VALUES (?,?)', (project['id'], now()))
            project_purge.purge(project['id'], project['name'])
            return j({'insights':[]})
        async def close(self): pass
    with pytest.raises(asyncio.CancelledError): asyncio.run(memory.MemoryWorker(lambda _: Client()).run_once(ignore_idle=True))
    assert many('SELECT * FROM learning_events') == [] and many('SELECT * FROM learning_insights') == []
    assert memory.record_event('late', 'chat', {}, project_id=project['id']) is None


@pytest.mark.parametrize('committed', [False, True])
def test_recovery_of_interrupted_or_committed_file_cleanup(committed):
    project = create_project('断电恢复')
    path = files_dir()/'original.txt'; path.write_text('保留的数据')
    staging = data_dir()/'tmp'/('project-purge-' + uid()); staging.mkdir(parents=True)
    (staging/'manifest.json').write_text(j({'project_id':project['id'], 'paths':[str(path)]}), encoding='utf-8')
    path.replace(staging/'0')
    if committed: execute('DELETE FROM projects WHERE id=?', (project['id'],))
    project_purge.retry_cleanup()
    assert not staging.exists()
    assert path.exists() is not committed
    if not committed: assert path.read_text() == '保留的数据'


def test_purge_uses_fk_ownership_for_new_extension_tables():
    project = create_project('扩展表')
    chat = conversations.create(project['id'], 'deepseek')
    execute('CREATE TABLE plugin_notes(id TEXT PRIMARY KEY,conversation_id TEXT REFERENCES conversations(id),content TEXT)')
    execute('INSERT INTO plugin_notes VALUES (?,?,?)', ('note', chat['id'], '扩展功能笔记'))
    recycle(project)
    project_purge.purge(project['id'], project['name'])
    assert many('SELECT * FROM plugin_notes') == []


def test_committed_cleanup_failure_retains_manifest_and_is_visible_until_retry(monkeypatch):
    project = create_project('占用的待清理文件')
    path = files_dir()/'owned.txt'; path.write_text('独占文件'); source(project, path); recycle(project)
    unlink = Path.unlink
    def occupied(item, *args, **kwargs):
        if item.name == '0' and item.parent.name.startswith('project-purge-'): raise PermissionError('占用')
        return unlink(item, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', occupied)
        assert project_purge.purge(project['id'], project['name'])['cleanup_pending'] is True
        staging = next((data_dir()/'tmp').glob('project-purge-*'))
        assert (staging/'manifest.json').exists() and (staging/'0').exists()
        assert TestClient(server.app).get('/api/recycle-bin/cleanup').json()['pending_count'] == 1
        assert TestClient(server.app).get('/api/recycle-bin/projects').json() == []
        assert staging.exists()
    project_purge.retry_cleanup()
    assert not staging.exists() and not path.exists() and project_purge.cleanup_status()['pending_count'] == 0


def test_cross_project_cascade_is_rejected_before_deleting_either_project():
    project, other = create_project('删除目标'), create_project('保护另一个项目')
    execute('CREATE TABLE plugin_shared(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),source_project_id TEXT REFERENCES projects(id) ON DELETE CASCADE)')
    execute('INSERT INTO plugin_shared VALUES (?,?,?)', ('reference', other['id'], project['id']))
    recycle(project)
    with pytest.raises(project_purge.PurgeConflict): project_purge.purge(project['id'], project['name'])
    assert one('SELECT * FROM plugin_shared') and len(many('SELECT * FROM projects')) == 2


@pytest.mark.parametrize('resource', [None, 'media'])
def test_cancelled_threads_cannot_write_files_after_permanent_deletion(resource):
    from studyforge.scheduling import execution_scope, local_work_pending, run_local, run_owned_io
    project = create_project('取消后仍在收尾')
    job = create_job(project['id'], 'import', {})
    started, finish = threading.Event(), threading.Event()
    directory = data_dir()/'tmp'/'downloads'/uid()
    path = directory/'late.txt'
    def operation():
        started.set()
        assert finish.wait(5)
        directory.mkdir(parents=True)
        path.write_text('后台线程尚未结束前禁止清理')
        return path
    async def run():
        async with execution_scope(project_id=project['id'], job_id=job):
            task = asyncio.create_task(run_owned_io(operation) if resource is None else run_local(resource, operation))
            while not started.is_set(): await asyncio.sleep(.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            recycle(project)
            try:
                assert local_work_pending(project['id'])
                with pytest.raises(project_purge.PurgeConflict, match='本地文件处理'): project_purge.purge(project['id'], project['name'])
            finally: finish.set()
            for _ in range(500):
                if not local_work_pending(project['id']): break
                await asyncio.sleep(.01)
            assert not local_work_pending(project['id']) and path.exists()
            assert one('SELECT path FROM job_file_outputs WHERE job_id=?', (job,))['path'] == str(path)
            project_purge.purge(project['id'], project['name'])
            assert not path.exists() and not directory.exists()
    asyncio.run(run())
