from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from studyforge import server


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_and_phone_load_shared_inspector_and_shell_contains_no_audit_content():
    for html in ('web/index.html', 'web/mobile/index.html'):
        source = (ROOT / html).read_text(encoding='utf-8')
        assert '/teaching_review.js' in source and '/teaching_review.css' in source
    worker = (ROOT / 'web/mobile/sw.js').read_text(encoding='utf-8')
    assert "'/teaching_review.js'" in worker and "'/teaching_review.css'" in worker
    assert 'studyforge-mobile-shell-0.0.1' in worker
    assert '/api/artifacts' not in worker
    with TestClient(server.app) as client:
        for asset in ('teaching_review.js', 'teaching_review.css'):
            response = client.get('/' + asset)
            assert response.status_code == 200 and len(response.content) > 1000


def test_all_guide_sections_have_navigation_and_describe_audit_limits():
    class Guide(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sections, self.links = set(), set()

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'section' and 'guide-section' in attrs.get('class', '').split():
                self.sections.add(attrs['id'])
            if tag == 'a' and attrs.get('href', '').startswith('#'):
                self.links.add(attrs['href'][1:])

    guide = (ROOT / 'web/help/guide.html').read_text(encoding='utf-8')
    parser = Guide()
    parser.feed(guide)
    assert parser.sections <= parser.links
    for text in ('教学核查记录', '不是正确性认证', '不自动把旧疑点算成新错误', '不写入学习画像'):
        assert text in guide
