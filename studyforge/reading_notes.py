"""Bind auxiliary AI notes to the exact original input, never batch ordinals.

A matched fingerprint proves which text was supplied, not that a note is true.
Legacy records remain usable as explicitly unassigned navigation. No model call
or duplicate source text is needed to establish this correspondence.
"""
from __future__ import annotations

import hashlib
import re

VERSION = '2026-10-21-reading-note-input-v1'


def input_scope(original: str) -> dict:
    return {'version': VERSION, 'sha256': hashlib.sha256(original.encode('utf-8')).hexdigest(),
            'characters': len(original)}


def _complete_prefix(text: str, budget: int) -> str:
    """Keep a complete Markdown prefix; do not cut a paragraph, code or math."""
    offset = end = 0
    fence = math = None
    for line in text.splitlines(keepends=True):
        offset += len(line)
        if offset > budget:
            break
        value = line.strip()
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker and not math:
            if fence is None:
                fence = (marker[1][0], len(marker[1]))
            elif marker[1][0] == fence[0] and len(marker[1]) >= fence[1]:
                fence = None
        elif not fence:
            if math == 'bracket':
                if r'\]' in line:
                    math = None
            elif math == 'dollar':
                if len(re.findall(r'(?<!\\)\$\$', line)) % 2:
                    math = None
            elif r'\[' in line and r'\]' not in line:
                math = 'bracket'
            elif len(re.findall(r'(?<!\\)\$\$', line)) % 2:
                math = 'dollar'
        if not value and not fence and not math:
            end = offset
    else:
        if not fence and not math:
            end = len(text)
    prefix = text[:end].rstrip()
    # A title without its following paragraph supplies no useful note content.
    prefix = re.sub(r'(?:^|\n)#{1,6}[^\n]*\s*$', '', prefix).rstrip()
    return prefix


def context(notes: list[dict], original: str, budget: int = 3000) -> tuple[str, dict]:
    """Select exact-input notes, or clearly labelled legacy overview notes.

    New notes for another slice are excluded even if their part numbers match.
    No source/position guessing or substring similarity establishes a match.
    A changed batch can simply rely on the complete original supplied separately.
    """
    if budget < 400:
        raise ValueError('阅读笔记输入预算至少为400字符')
    scope = input_scope(original)
    matched, legacy = [], []
    receipt = {'version': VERSION, 'original_input': scope, 'total_notes': len(notes),
               'matched_notes': 0, 'legacy_notes': 0, 'unmatched_notes': 0,
               'invalid_notes': 0, 'included': [], 'characters': 0,
               'meaning': 'input_correspondence_not_note_accuracy'}
    for note in notes:
        if not isinstance(note, dict) or not isinstance(note.get('text'), str):
            receipt['invalid_notes'] += 1
            continue
        if 'input_scope' not in note:
            legacy.append(note)
            continue
        stamp = note['input_scope']
        if (not isinstance(stamp, dict) or stamp.get('version') != VERSION
                or type(stamp.get('characters')) is not int or stamp['characters'] < 0
                or not isinstance(stamp.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', stamp['sha256'])):
            receipt['invalid_notes'] += 1
        elif stamp == scope:
            matched.append(note)
        else:
            receipt['unmatched_notes'] += 1
    receipt.update(matched_notes=len(matched), legacy_notes=len(legacy))
    if not notes:
        receipt['reason'] = 'no_notes'
        return '', receipt
    if matched:
        candidates = matched
        receipt['reason'] = 'exact_original_input'
        label = ('【与本部分完整原文输入对应的AI阅读笔记】指纹仅确认通读输入相同，不证明笔记正确；'
                 '笔记辅助组织，结论与条件以本次完整原文为准。\n')
    elif legacy:
        candidates = legacy
        receipt['reason'] = 'legacy_unassigned'
        label = ('【旧版整体AI阅读笔记，未确认对应当前分段】这些笔记未记录通读原文分段指纹；'
                 '即使部分编号相同也不能认定属于本部分。仅作整体导航，不能据此添加或改变本部分的条件与结论。\n')
    else:
        receipt['reason'] = 'no_matching_original_input'
        label = ('【阅读笔记对应关系】现有笔记没有与本部分完全相同的通读输入记录，未按部分编号猜配；'
                 '请直接依据下方完整原文讲解，不推断笔记已经覆盖本部分。')
        receipt['characters'] = len(label)
        return label, receipt
    ending = '\n【笔记节选范围】仅列入完整段落；未列出的笔记不代表原资料没有相关内容。完整原文另行提供。'
    blocks, seen = [], set()
    used = len(label) + len(ending)
    for note in candidates:
        fingerprint = hashlib.sha256(note['text'].encode('utf-8')).hexdigest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        # Part numbers describe the saved reading, not the generation slice.
        part = note.get('part')
        prefix = f"[通读记录{part if type(part) is int and part > 0 else '（未编号）'}]\n"
        text = _complete_prefix(note['text'], budget - used - len(prefix) - 2)
        if not text:
            continue
        blocks.append(prefix + text)
        used += len(prefix) + len(text) + 2
        receipt['included'].append({'reading_part': part if type(part) is int else None,
            'text_sha256': fingerprint, 'start': 0, 'end': len(text), 'excerpted': len(text) < len(note['text'])})
    result = label + '\n\n'.join(blocks) + ending
    if not blocks:
        result = label + '本次预算内没有可完整提供的笔记段落；请依据完整原文。'
    receipt['characters'] = len(result)
    assert len(result) <= budget
    return result, receipt
