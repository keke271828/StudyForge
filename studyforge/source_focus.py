"""Question-focused excerpts of already authorized, fully prepared originals.

This is local lexical navigation, not another AI reading or a semantic proof.
Offsets always address the supplied digest. No file, database or network access
is performed here; document generation continues to receive its complete input.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import re

VERSION = '2026-10-26-chat-original-focus-v1'
LIMIT = 36000
_HEADER = re.compile(r'^\[来源 ([^\n]+)｜([^\n]+?)\](?: \[资料ID:([^\n]+?)\])?\n', re.M)
_LINE = re.compile(r'[^\n]*\n|[^\n]+$')
_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$', re.M)
_BLANK = re.compile(r'\s*')
_MATH = re.compile(r'(?<!\\)\$\$|(?<![\\$])\$(?!\$)|\\[\[\]()]')


@dataclass(frozen=True)
class Unit:
    start: int
    end: int
    header: str
    header_start: int
    name: str
    source_id: str | None
    safe_before: bool
    safe_after: bool


def _ranges(text, start, end, state, target=4000):
    """Cut only on blank lines outside complete fenced code and math."""
    left = start
    fence, formula = state
    safe_before = not fence and formula is None
    for line in _LINE.finditer(text, start, end):
        marker = _FENCE.match(text, line.start(), line.end())
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and _BLANK.fullmatch(text, marker.start(2), line.end()):
                fence = None
        elif marker and formula is None:
            fence = (marker[1][0], len(marker[1]))
        else:
            for match in _MATH.finditer(text, line.start(), line.end()):
                token = match[0]
                if formula is None and token in ('$', '$$', r'\[', r'\('):
                    formula = token
                elif token == {'$':'$', '$$':'$$', r'\[':r'\]', r'\(':r'\)'}.get(formula):
                    formula = None
        right = line.end()
        if _BLANK.fullmatch(text, line.start(), line.end()) and not fence and formula is None and right-left >= target:
            yield left, right, safe_before, True
            left = right
            safe_before = True
    if left < end:
        yield left, end, safe_before, not fence and formula is None
    state[:] = [fence, formula]


def units(digest):
    headers = list(_HEADER.finditer(digest))
    result = []
    previous = None
    state = [None,None]
    for index, header in enumerate(headers):
        end = headers[index+1].start() if index+1 < len(headers) else len(digest)
        identity = header[3] or header.start()
        if identity != previous:
            state[:] = [None,None]
        # A provenance line itself is never lexical evidence for a topic.
        for start, stop, before, after in _ranges(digest, header.end(), end, state):
            result.append(Unit(start, stop, header[0].rstrip(), header.start(), header[1], header[3], before, after))
        previous = identity
    return result


def _neighbours(items, index):
    result = [index]
    current = items[index]
    for neighbour in (index-1, index+1):
        if not 0 <= neighbour < len(items):
            continue
        other = items[neighbour]
        # Across page/segment boundaries require an explicit source identity.
        if (current.header_start == other.header_start or
                (current.source_id and current.source_id == other.source_id)):
            result.append(neighbour)
    left, right = min(result), max(result)
    # A file parser may have divided one fenced block/formula between pages or
    # line segments. Extend to both delimiters, or omit this neighbourhood.
    while not items[left].safe_before:
        if left == 0 or not current.source_id or items[left-1].source_id != current.source_id:
            return None
        left -= 1
        result.append(left)
    while not items[right].safe_after:
        if right+1 == len(items) or not current.source_id or items[right+1].source_id != current.source_id:
            return None
        right += 1
        result.append(right)
    return result


def _parts(digest, items, selected):
    groups = []
    for index in sorted(selected):
        unit = items[index]
        if groups and groups[-1][0].header_start == unit.header_start and groups[-1][2] == unit.start:
            groups[-1] = (groups[-1][0], groups[-1][1], unit.end)
        else:
            groups.append((unit, unit.start, unit.end))
    blocks, receipt = [], []
    for unit, start, end in groups:
        position = f'【原文片段；本次完整输入字符 {start+1}–{end}；片段之间可能省略内容】\n'
        blocks.append(unit.header + '\n' + position + digest[start:end])
        receipt.append({'source_id':unit.source_id, 'name':unit.name, 'locator':unit.header,
            'start':start, 'end':end, 'sha256':hashlib.sha256(digest[start:end].encode()).hexdigest()})
    return '\n\n'.join(blocks), receipt


def _identity(digest, included):
    from . import source_origins as origin
    if not digest.startswith(origin.BEGIN):
        return ''
    raw, marker, _ = digest[len(origin.BEGIN):].partition(origin.END)
    if not marker:
        return ''
    try:
        value = json.loads(raw)
    except ValueError:
        return ''
    if not isinstance(value, dict) or value.get('version') != origin.VERSION or not isinstance(value.get('materials'), list):
        return ''
    ids = {item['source_id'] for item in included if item['source_id']}
    names = {item['name'] for item in included}
    return origin.header([entry for entry in value['materials'] if isinstance(entry, dict) and
        (entry.get('source_id') in ids if entry.get('source_id') else entry.get('name') in names)])


def _navigation(notes, budget=2000):
    from .reading_notes import _complete_prefix
    result = []
    for note in notes:
        if not isinstance(note, dict) or not isinstance(note.get('text'), str):
            continue
        text = _complete_prefix(note['text'][:budget+1], budget)
        if text:
            result.append(text)
            budget -= len(text)+2
        if budget < 200:
            break
    return ('\n【通读时保存的AI笔记，仅供导航，不是原文证据】\n'+'\n\n'.join(result)) if result else ''


def prepare(digest, query, notes=(), *, limit=LIMIT):
    if limit < 1000:
        raise ValueError('原文定位预算至少为1000字符')
    from .library import automatic_query_terms, query_keywords
    keywords = query_keywords(automatic_query_terms(query))
    patterns = [(term, re.compile(r'(?<![a-z0-9_])'+re.escape(term)+r'(?![a-z0-9_])', re.I)
                 if term.isascii() else None) for term in keywords]
    items = units(digest)
    matches = []
    frequency = Counter()
    for unit in items:
        found = {term for term, pattern in patterns if (pattern.search(digest, unit.start, unit.end)
                 if pattern else digest.find(term, unit.start, unit.end) >= 0)}
        matches.append(found)
        frequency.update(found)
    ranked = sorted((index for index, found in enumerate(matches) if found), key=lambda index:(-sum(
        len(term)**2 * math.log2(2+len(items)/(1+frequency[term])) for term in matches[index]), index))
    # Try each file's best hit first, then additional evidence in rank order.
    first, extra, seen = [], [], set()
    for index in ranked:
        key = items[index].source_id or (items[index].name, items[index].header_start)
        (extra if key in seen else first).append(index)
        seen.add(key)
    selected, skipped = set(), 0
    for index in (first[:8]+extra[:16]):
        neighbours = _neighbours(items, index)
        if neighbours is None:
            skipped += 1
            continue
        proposed = selected | set(neighbours)
        if proposed == selected:
            continue
        if sum(items[i].end-items[i].start for i in proposed) > limit:
            skipped += 1
            continue
        body, included = _parts(digest, items, proposed)
        if len(body)+len(_identity(digest, included)) <= limit:
            selected = proposed
        else:
            skipped += 1
    body, included = _parts(digest, items, selected)
    prefix = ('【长资料的相关原文片段，不是全文】\n'
        '下面从本次获准且已完成准备的资料输入中按当前问题定位，保留相邻原文；'
        '检索命中不证明片段足以回答，未列出的定义、条件或证明不能视为已核对。'
        '若依据不足，指出缺少哪一处并请求定位或使用获准的原文读取工具；不能用AI笔记代替原文。\n')
    if not body:
        prefix += '本次没有找到预算内可完整提供的明确命中片段；请先确认具体概念或原文位置，不猜测原文结论。\n'
    context = prefix + _identity(digest, included) + body + _navigation(notes)
    return context, {'version':VERSION, 'input_sha256':hashlib.sha256(digest.encode()).hexdigest(),
        'input_characters':len(digest), 'context_sha256':hashlib.sha256(context.encode()).hexdigest(),
        'context_characters':len(context), 'excerpt_limit':limit, 'units':len(items),
        'matched_units':len(ranked), 'included':included, 'skipped_neighbourhoods':skipped,
        'reason':'matched' if included else 'no_complete_match', 'model_calls':0}
