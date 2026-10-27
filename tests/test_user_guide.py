from fastapi.testclient import TestClient
from html.parser import HTMLParser
from pathlib import Path

from studyforge import server
from studyforge.mobile_access import MobileManager


def test_guide_is_available_before_phone_pairing_without_exposing_other_files():
    manager = MobileManager(server.app)
    manager.addresses = ['127.0.0.1']
    with TestClient(manager.gateway, base_url='https://127.0.0.1', client=('127.0.0.1', 14000)) as client:
        for path in ('/user_guide.js', '/user_guide.css', '/source_evidence.js', '/source_evidence.css', '/teaching_review.js', '/teaching_review.css', '/help/guide.html', '/help/guide.js', '/help/guide.css'):
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)
            assert len(response.content) > 500
        response = client.get('/help/guide.html')
        assert '零基础' in response.text
        assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
        assert "frame-ancestors 'self'" in response.headers['Content-Security-Policy']
        assert client.get('/').headers['X-Frame-Options'] == 'DENY'
        for path in ('/help/private.txt', '/index.html', '/desktop_startup.js', '/help/../index.html'):
            assert client.get(path).status_code == 404, path
        assert client.get('/api/projects').status_code == 401


def test_desktop_bundle_includes_offline_guide():
    with TestClient(server.app) as client:
        response = client.get('/help/guide.html')
        assert response.status_code == 200
        for title in ('第一次使用：走通一遍', '只读某一页的一段文字', '交作业的完整流程', '安卓手机连接与使用'):
            assert title in response.text
        assert '检查这份成果依据了什么' in response.text
        assert 'data-open-user-guide' in client.get('/').text


def test_every_guide_link_has_a_topic_and_tasks_are_reachable():
    class Guide(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = []
            self.targets = []
            self.sections = []
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if 'id' in values:
                self.ids.append(values['id'])
            if tag == 'section' and 'guide-section' in values.get('class', '').split():
                self.sections.append(values['id'])
            if tag == 'a' and values.get('href', '').startswith('#'):
                self.targets.append(values['href'][1:])
    guide = Guide()
    root = Path(__file__).resolve().parents[1]
    guide.feed((root / 'web/help/guide.html').read_text(encoding='utf-8'))
    assert len(guide.ids) == len(set(guide.ids))
    assert len(guide.sections) == 19
    assert set(guide.targets) == set(guide.sections)
    assert all(guide.targets.count(task) >= 2 for task in
               ('start', 'materials', 'outputs', 'homework', 'library', 'troubleshooting'))
