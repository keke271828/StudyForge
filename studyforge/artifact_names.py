"""Readable download names for new and previously generated learning files."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .teaching import headings

ALIASES = {'word': 'docx', 'ppt': 'pptx', 'mindmap': 'mm', 'anki': 'apkg'}
ROLES = ('AI讲解', 'AI 讲解', '配套习题（无答案）', '配套习题', '进阶习题（无答案）',
         '进阶习题', '习题与解析', '原题与答案解析', '批改与错题讲解', '视频原文档', '编程作业审查记录', '编程作业未发布·审查记录')


def _topic(value: str) -> str:
    value = value.strip()
    if re.match(r'^https?://', value, re.I) or re.fullmatch(r'[\da-f]{32}|[\da-f-]{36}', value, re.I):
        return ''
    value = value.replace('**', '').replace('__', '').strip()
    for _ in range(3):
        previous = value
        for role in ROLES:
            if value.endswith(role):
                value = value[:-len(role)].rstrip(' ·_-—')
                break
        suffix = Path(value).suffix.lower().lstrip('.')
        if suffix in {'pdf', 'docx', 'pptx', 'txt', 'md', 'mp4', 'mov', 'mkv', 'webm', 'avi',
                      'mp3', 'wav', 'm4a', 'flac', 'ogg', 'apkg', 'mm', 'opml', 'xmind', 'ipynb',
                      'py', 'js', 'ts', 'tsx', 'jsx', 'cpp', 'c', 'h', 'java', 'rs', 'go', 'cs', 'sql',
                      'm', 'wl', 'wls', 'slx', 'zip', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'html', 'htm',
                      'json', 'csv', 'xlsx', 'tex'}:
            value = value[:-(len(suffix)+1)]
        if value == previous:
            break
    value = value.strip()
    return '' if re.fullmatch(r'[\da-f]{32}|[\da-f-]{36}', value, re.I) else value


def explanation_title(document: str, fallback: str) -> str:
    for _, level, title in headings(document):
        if level == 1 and _topic(title):
            return _topic(title) + '·AI 讲解'
    return (_topic(fallback) or '学习资料') + '·AI 讲解'


def download_filename(title: str, kind: str, fmt: str, stored_name: str, created_at: str,
                      source_names: list[str] | None = None, project_name: str = '') -> str:
    label = {'explanation': 'AI讲解', 'original': '视频原文档', 'solutions': '习题与解析',
             'exercise': '进阶习题（无答案）' if '进阶' in title else '配套习题（无答案）',
             'grading':'批改与错题讲解', 'review': title or '审查记录'}.get(kind, '')
    topic = _topic(title)
    if not topic:
        topic = next((name for original in source_names or [] if (name := _topic(original))), '')
    if not topic:
        topic = _topic(project_name) or '学习成果'
    component = '_'.join(part for part in (topic, label) if part)
    component = unicodedata.normalize('NFKC', component)
    component = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]', '_', component)
    component = re.sub(r'\s+', ' ', component).strip(' .')[:100].rstrip(' .') or '学习成果'
    if re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', component, re.I):
        component = '学习成果_' + component
    try:
        stamp = datetime.fromisoformat(created_at).astimezone().strftime('%Y-%m-%d_%H-%M-%S')
    except (ValueError, TypeError):
        stamp = ''
    extension = ALIASES.get(fmt.lower(), fmt.lower())
    if not re.fullmatch(r'[a-z0-9]{1,12}', extension) or extension == 'file':
        extension = Path(stored_name).suffix.lstrip('.').lower()
    ending = '.' + extension if extension else ''
    return component + ('_' + stamp if stamp else '') + ending


def renamed_filename(name: str, fmt: str, stored_name: str) -> str:
    """Preserve the user's chosen name while keeping the actual file extension."""
    extension = ALIASES.get(fmt.lower(), fmt.lower())
    if not re.fullmatch(r'[a-z0-9]{1,12}', extension) or extension == 'file':
        extension = Path(stored_name).suffix.lstrip('.').lower()
    name = unicodedata.normalize('NFKC', name.strip())
    if extension and name.lower().endswith('.' + extension):
        name = name[:-(len(extension) + 1)]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip(' .')[:100].rstrip(' .')
    if not name:
        raise ValueError('请输入有效的文件名称')
    if re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I):
        name = '学习成果_' + name
    return name + ('.' + extension if extension else '')
