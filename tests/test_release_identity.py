"""The public release, backend, and shipped introduction must identify one product."""
import json
from pathlib import Path
import tomllib

from studyforge import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_product_versions_agree():
    package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
    lock = json.loads((ROOT / 'package-lock.json').read_text(encoding='utf-8'))
    python = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    from studyforge.server import app
    assert {package['version'], lock['version'], lock['packages']['']['version'],
            python['project']['version'], __version__, app.version} == {'0.0.1'}


def test_app_introductions_are_current_and_chinese():
    for relative in ('web/index.html', 'web/mobile/index.html', 'web/help/guide.html'):
        content = (ROOT / relative).read_text(encoding='utf-8')
        assert '0.0.1' in content, relative
        assert 'lang="en"' not in content, relative
        assert '0.4.6' not in content and '0.3.4' not in content, relative


def test_release_notes_are_current_and_bilingual():
    notes = (ROOT / 'docs/Release-0.0.1.md').read_text(encoding='utf-8')
    for name in ('StudyForge-Setup-0.0.1.exe', 'StudyForge-source-0.0.1.zip'):
        assert name in notes
    assert '## Features' in notes and '## 功能' in notes
    assert '在0.4.' not in notes
