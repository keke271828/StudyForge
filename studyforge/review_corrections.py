"""Bounded atomic audit edits with narrowly scoped prose-format aliases."""
from __future__ import annotations

import re
import hashlib


_SOURCE = re.compile(r'\[(?:[^\]\n]*[｜|][^\]\n]*|(?:来源|Source)\s*[:：][^\]\n]*)\]', re.I)
_LINK = re.compile(r'\[[^\]\n]*\]\([^\s)]+\)|https?://[^\s<>)\]]+', re.I)
_DOUBLE_QUOTES = '"“”'
_QUOTE_KEY = str.maketrans({'“': '"', '”': '"'})
_LETTER_MATH = re.compile(r'(?<![\\$])\$([A-Za-z])\$(?!\$)')


def _math_label_anchor(document, before):
    """Ignore only $ wrappers of single Latin labels in a Chinese sentence.

    Formula contents, spacing, primes and every prose character stay literal.
    The caller additionally requires the located sentence to belong to a plain
    paragraph. This is not a mathematical-equivalence or fuzzy-text matcher.
    """
    if (len(before) < 40 or len(re.findall(r'[\u4e00-\u9fff]', before)) < 12 or before[-1] not in '。！？' or
            any(char in before for char in '\r\n`') or '$$' in before or '\\(' in before or '\\[' in before or
            _SOURCE.search(before) or _LINK.search(before)):
        return None
    labels = list(_LETTER_MATH.finditer(before))
    if not 1 <= len(labels) <= 8:
        return None
    parts, previous = [], 0
    for label in labels:
        parts.append(re.escape(before[previous:label.start()]))
        symbol = re.escape(label[1])
        parts.append(r"(?<![A-Za-z0-9_$\\'’′^])(?:\$" + symbol + r"\$|" + symbol + r")(?![A-Za-z0-9_$'’′^])")
        previous = label.end()
    parts.append(re.escape(before[previous:]))
    found = re.finditer(''.join(parts), document)
    match = next(found, None)
    if match is None or next(found, None) is not None:
        return None
    start, end = match.span()
    if start and document[start-1] not in '\n。！？；':
        return None
    return start, end, 'math_labels'


def _anchor(document, before):
    """Prefer literal matching, then try two narrowly bounded prose aliases.

    Quote aliases require a whole long line; single-letter math wrappers require
    a complete long Chinese sentence. Both must belong to a plain paragraph,
    checked by the renderer once candidates are collected. No words, whitespace,
    formula contents, numeric values or apostrophe/prime symbols are normalized.
    """
    count = document.count(before)
    if count == 1:
        start = document.index(before)
        return start, start+len(before), False
    if count: return None
    math_anchor = _math_label_anchor(document, before)
    if math_anchor: return math_anchor
    if len(before)<40 or not any(char in before for char in _DOUBLE_QUOTES): return None
    if (len(re.findall(r'[\u4e00-\u9fff]', before))<12 or before[-1] not in '。！？' or
            any(char in before for char in '\r\n$`\\=<>^±∑×÷|') or _SOURCE.search(before) or _LINK.search(before)):
        return None
    pattern = ''.join('["“”]' if char in _DOUBLE_QUOTES else re.escape(char) for char in before)
    matches = re.finditer(pattern, document)
    found = next(matches, None)
    if found is None or next(matches, None) is not None: return None
    start, end = found.span()
    if start and document[start-1]!='\n': return None
    if end<len(document) and document[end]!='\n' and document[end:end+2]!='\r\n': return None
    return start, end, True


def _structure(document):
    from .document_render import blocks, validate_document_text
    validate_document_text(document)
    headings, quotes = [], []
    # Cell tokenization is export work. The edit guard only needs protected
    # headings/quotes and balanced code/display-math fences.
    for kind, value in blocks(document, parse_tables=False):
        if kind == 'heading': headings.append(value)
        elif kind in ('quote', 'quote_math'): quotes.append((kind, value))
    # Compare the whole document, so even an anchor inside a page number or
    # source name cannot bypass provenance protection.
    return headings, quotes, _SOURCE.findall(document), _LINK.findall(document)


def _apply(document, edits):
    for start, end, after, _ in sorted(edits, reverse=True):
        document = document[:start] + after + document[end:]
    return document


def apply_local_corrections(document: str, corrections, issues: list[dict], *, match_receipts=None,
                            passage_registry=None) -> tuple[str, list[int]]:
    """Apply every proposed edit of an issue together, or retain its warning.

    Anchors always refer to the original text. Conflicting issues are both
    rejected, irrespective of patch order. An unrelated valid group may still
    proceed when another group is malformed. Application is not verification
    that the model's suggested replacement is factually correct.
    """
    if not isinstance(corrections, list) or not corrections or len(corrections) > 8: return document, []
    from .lesson_cautions import records
    protected_cautions=records([document])
    from .review_passages import validated_locations
    registered = validated_locations(document,passage_registry) if any(isinstance(p,dict) and 'passage_id' in p for p in corrections) else {}
    groups, rejected, aliases, receipts = {}, set(), [], []
    for patch in corrections:
        # An unassigned edit could belong to any issue: do not hide a warning
        # by applying only the attributable part of a malformed response.
        if not isinstance(patch, dict): return document, []
        index = patch.get('issue_index')
        if type(index) is not int or not 0 <= index < len(issues): return document, []
        groups.setdefault(index, [])
        passage_id = patch.get('passage_id')
        if 'passage_id' in patch:
            if (not isinstance(passage_id,str) or 'before' in patch or passage_id not in registered):
                rejected.add(index)
                continue
            start,end=registered[passage_id]
            before=document[start:end]
            anchor=(start,end,False)
        else:
            before=patch.get('before')
            anchor=None
        after = patch.get('after')
        if (not isinstance(before, str) or not 0 < len(before) <= 1800 or
                not isinstance(after, str) or not after.strip() or len(after) > 2600 or
                before == after):
            rejected.add(index)
            continue
        if 'passage_id' not in patch:anchor=_anchor(document,before)
        if not anchor:
            rejected.add(index)
            continue
        start, end, alias = anchor
        if any(start < item['end'] and end > item['start'] for item in protected_cautions):
            rejected.add(index)
            continue
        if alias:
            raw = document[start:end]
            same = (_LETTER_MATH.sub(r'\1', raw) == _LETTER_MATH.sub(r'\1', after) if alias == 'math_labels'
                    else raw.translate(_QUOTE_KEY) == after.translate(_QUOTE_KEY))
            if same:
                rejected.add(index)
                continue
            aliases.append((index, raw, alias))
        groups[index].append((start, end, after, index))
        receipts.append({'issue_index': index, 'start': start, 'end': end,
                         'mode': 'registered_passage' if 'passage_id' in patch else 'single_letter_math_delimiters' if alias == 'math_labels' else 'prose_quote_typography' if alias else 'literal',
                         'reported_before_sha256': None if 'passage_id' in patch else hashlib.sha256(before.encode()).hexdigest(),
                         **({'passage_id':passage_id,'document_sha256':passage_registry['document_sha256'],
                             'coordinate_unit':'unicode_code_points'} if 'passage_id' in patch else {}),
                         'original_sha256': hashlib.sha256(document[start:end].encode()).hexdigest()})
    if aliases:
        from .document_render import blocks
        try:
            paragraphs = [value for kind,value in blocks(document,parse_tables=False) if kind=='paragraph']
        except ValueError:
            return document, []
        rejected.update(index for index,raw,alias in aliases
                        if not any(raw in value if alias == 'math_labels' else raw == value for value in paragraphs))
    anchored = [edit for group in groups.values() for edit in group]
    for position, (start, end, _, index) in enumerate(anchored):
        for other_start, other_end, _, other_index in anchored[position + 1:]:
            if start < other_end and end > other_start:
                rejected.update((index, other_index))
    if not any(group for index, group in groups.items() if index not in rejected): return document, []
    try: original_structure = _structure(document)
    except ValueError: return document, []
    for index, edits in groups.items():
        if index in rejected: continue
        try:
            if _structure(_apply(document, edits)) != original_structure: rejected.add(index)
        except ValueError: rejected.add(index)
    selected = [edit for index, group in groups.items() if index not in rejected for edit in group]
    candidate = _apply(document, selected)
    try:
        if _structure(candidate) != original_structure: return document, []
    except ValueError: return document, []
    resolved = sorted(index for index, group in groups.items() if group and index not in rejected)
    if match_receipts is not None:
        match_receipts.extend(item for item in receipts if item['issue_index'] in resolved)
    return candidate, resolved
