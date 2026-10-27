"""Regression cases found by the final requirements audit."""
import asyncio
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from studyforge import ai, coding, server
from studyforge.config import data_dir
from studyforge.db import create_project, execute, j, now, one, uid


def test_parallel_setting_changes_preserve_every_field(monkeypatch):
    original = ai.settings

    def slow_read():
        value = original()
        time.sleep(.025)  # Real overlapping read/merge/write, without a deadlocking barrier.
        return value

    monkeypatch.setattr(ai, 'settings', slow_read)
    changes = [{'ui_theme': 'night'}, {'learning_mode': 'overview'}, {'review_mode': 'strict'},
               {'deepseek_model': 'audit-model'}, {'ui_text_size': 'large'}, {'ui_focus': True}]
    with ThreadPoolExecutor(max_workers=len(changes)) as pool:
        list(pool.map(ai.save_settings, changes))
    actual = original()
    for change in changes:
        for key, value in change.items():
            assert actual[key] == value


@pytest.mark.parametrize('value', [{'review_mode': []}, {'image_api_base': []},
                                   {'voice_language': 'invalid'}, {'auto_select_imports': 'false'}])
def test_invalid_setting_types_are_client_errors(value):
    response = TestClient(server.app).put('/api/settings', json=value)
    assert response.status_code == 400


def test_failed_atomic_settings_save_keeps_previous_file(monkeypatch):
    ai.save_settings({'ui_theme': 'night'})
    before = (data_dir() / 'settings.json').read_bytes()
    monkeypatch.setattr('os.replace', lambda *args: (_ for _ in ()).throw(OSError('disk failure')))
    with pytest.raises(OSError, match='disk failure'):
        ai.save_settings({'ui_theme': 'forest'})
    assert (data_dir() / 'settings.json').read_bytes() == before
    assert not list(data_dir().glob('.settings-*.tmp'))


def test_docker_launch_failure_does_not_grade_student_zero(monkeypatch):
    monkeypatch.setattr(coding, '_docker_available', lambda: True)
    monkeypatch.setattr(coding.subprocess, 'run', lambda *a, **k:
                        subprocess.CompletedProcess(a[0], 125, '', 'image download failed'))
    result = coding._run_python_tests('pass', 'pass')
    assert not result['ran'] and result.get('score') is None


def test_timeout_removes_only_the_owned_container(monkeypatch):
    monkeypatch.setattr(coding, '_docker_available', lambda: True)
    calls = []

    def run(command, **options):
        calls.append(command)
        if command[1] == 'run':
            raise subprocess.TimeoutExpired(command, 90)
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(coding.subprocess, 'run', run)
    result = coding._run_python_tests('pass', 'pass')
    assert result['ran'] and result['score'] == 0
    launch = next(command for command in calls if command[1] == 'run')
    container = launch[launch.index('--name') + 1]
    assert container.startswith('studyforge-grade-')
    assert ['docker', 'rm', '-f', container] in calls


def make_assignment():
    project = create_project('审计编程')
    assignment = uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
            (assignment, project['id'], '[]', '乘法',
             j([{'index': 0, 'question': '返回 a*b', 'topic': '乘法', 'language': 'python'}]),
             j([{'solution': 'def f(a,b): return a*b', 'test_code': 'pass'}]), 1, 'assigned', now()))
    return assignment


def test_container_grading_keeps_event_loop_responsive(monkeypatch):
    def slow_tests(*args):
        time.sleep(.2)
        return {'ran': True, 'passed': True, 'score': 100}

    class Grader:
        async def complete(self, *args, **kwargs):
            return json.dumps({'score': 100, 'feedback': '正确', 'issues': []})

    monkeypatch.setattr(coding, '_run_python_tests', slow_tests)
    assignment = make_assignment()

    async def check():
        grading = asyncio.create_task(coding.grade_code(Grader(), assignment, 'def f(a,b): return a*b'))
        await asyncio.sleep(.03)
        assert not grading.done(), 'The container test blocked the entire async service.'
        await grading

    asyncio.run(check())


@pytest.mark.parametrize('score', [float('nan'), float('inf'), True, -1, 101])
def test_invalid_static_grade_is_not_recorded(monkeypatch, score):
    monkeypatch.setattr(coding, '_run_python_tests', lambda *args: {'ran': True, 'passed': True, 'score': 100})

    class Grader:
        async def complete(self, *args, **kwargs):
            return json.dumps({'score': score, 'feedback': '评分', 'issues': []})

    with pytest.raises(RuntimeError, match='分数'):
        asyncio.run(coding.grade_code(Grader(), make_assignment(), 'pass'))
    assert one('SELECT count(*) AS count FROM submissions')['count'] == 0


def test_two_simultaneous_coding_submissions_record_only_one_final_grade(monkeypatch):
    monkeypatch.setattr(coding, '_run_python_tests', lambda *args: {'ran': True, 'passed': True, 'score': 100})
    assignment = make_assignment()

    async def check():
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        class Grader:
            async def complete(self, *args, **kwargs):
                nonlocal calls
                calls += 1
                entered.set()
                await release.wait()
                return json.dumps({'score': 100, 'feedback': '正确', 'issues': []})

        first=asyncio.create_task(coding.grade_code(Grader(),assignment,'pass'))
        await asyncio.wait_for(entered.wait(),timeout=2)
        # A duplicate submission must be rejected before paying for a second
        # model call, while the first review is still in progress.
        duplicate=await asyncio.gather(coding.grade_code(Grader(),assignment,'pass'),return_exceptions=True)
        release.set()
        responses=[await first,*duplicate]
        assert calls==1
        assert sum(isinstance(value, dict) for value in responses) == 1
        assert sum(isinstance(value, ValueError) for value in responses) == 1
        assert one('SELECT count(*) AS count FROM submissions')['count'] == 1

    asyncio.run(check())


def test_changed_media_is_not_explained_using_old_transcript(tmp_path):
    from studyforge.materials import file_sha256, read_original_sources
    original = tmp_path / 'media.mp4'
    original.write_bytes(b'original video')
    record = {'id':'test-media', 'name':'视频.mp4', 'original_path':str(original),
              'segments':[{'locator':'0-10 秒','text':'旧转录','meta':{'original_media_sha256':file_sha256(original)}}]}
    assert read_original_sources([record])[0]['segments'][0]['text'] == '旧转录'
    original.write_bytes(b'changed video')
    with pytest.raises(ValueError, match='原转录和画面不再对应'):
        read_original_sources([record])
