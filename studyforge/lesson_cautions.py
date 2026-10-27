"""Carry visible review records across bounded teaching handoffs, without AI."""
from __future__ import annotations

import re


_KINDS = {
    '待核实事项': 'unresolved', 'items requiring verification': 'unresolved',
    '来源定位需核对': 'unresolved', 'source citations requiring verification': 'unresolved',
    '局部代数核对提示': 'unresolved', 'local algebra checks to confirm': 'unresolved',
    '核查说明': 'review_status', 'review note': 'review_status',
}


def records(chapters):
    from .teaching import headings
    result = []
    for number, chapter in enumerate(chapters, 1):
        outline = headings(chapter)
        for index, (start, depth, title) in enumerate(outline):
            name = re.split(r'\s*[/｜|]\s*', title, maxsplit=1)[0]
            name = re.sub(r'[（(]待核对[）)]$', '', name).strip().casefold()
            kind = _KINDS.get(name)
            if not kind: continue
            end = next((offset for offset, level, _ in outline[index+1:] if level <= depth), len(chapter))
            body = chapter.find('\n', start, end)
            if body < 0 or not chapter[body+1:end].strip(): continue
            result.append({'chapter': number, 'start': start, 'end': end, 'kind': kind})
    return result


def receipt(items, included=None):
    selected = items if included is None else [items[index] for index in included]
    return {'caution_sections_total': len(items), 'caution_sections_included': len(selected),
        'caution_sections_omitted': len(items)-len(selected),
        'unresolved_sections_total': sum(item['kind'] == 'unresolved' for item in items),
        'unresolved_chapters': sorted({item['chapter'] for item in items if item['kind'] == 'unresolved'}),
        'caution_chapters_included': sorted({item['chapter'] for item in selected})}


def retain_records(revised, original):
    """A rewrite cannot establish that an older visible caution was resolved.

    Keep exact record sections unless they already survive verbatim. These
    records remain historical, unverified limitations, not new judgments.
    """
    from .teaching import headings,summary_section
    from collections import Counter,defaultdict
    items=records([original]);rewritten=records([revised]);missing=[]
    available=Counter(revised[item['start']:item['end']].strip() for item in rewritten)
    for item in items:
        text=original[item['start']:item['end']].strip()
        if available[text]:available[text]-=1
        else:missing.append(dict(item,text=text))
    info={'previous_sections':len(items),'restored_sections':len(missing),
          'meaning':'retained_prior_cautions_not_new_verification'}
    if not missing:return revised,info
    # A newly written "all verified" under the same unique notice heading is
    # still an unsupported rewrite, not grounds to clear the original record.
    def key(text):
        title=headings(text)[0][2]
        return re.split(r'\s*[/｜|]\s*',title,maxsplit=1)[0].casefold()
    def outermost(entries):
        roots=[]
        for item in sorted(entries,key=lambda row:(row['start'],-row['end'])):
            if not roots or item['start']>=roots[-1]['end']:roots.append(item)
        return roots
    old_keys=Counter(key(original[item['start']:item['end']]) for item in items)
    by_key=defaultdict(list)
    for item in outermost(rewritten):by_key[key(revised[item['start']:item['end']])].append(item)
    replacements=[];append=[]
    # Restoring an enclosing record also restores its nested records. Keep
    # their counts, but do not append a second copy of each nested section.
    for item in outermost(missing):
        text=item['text']
        name=key(text)
        matches=by_key[name]
        if old_keys[name]==1 and len(matches)==1:
            replacements.append((matches[0]['start'],matches[0]['end'],text))
        else:append.append(text)
    if replacements:
        pieces=[];cursor=0
        for start,end,text in sorted(replacements):
            pieces.extend((revised[cursor:start],text+'\n\n'));cursor=end
        pieces.append(revised[cursor:]);revised=''.join(pieces)
    if not append:return revised.strip(),info
    section=summary_section(revised)
    position=section[0] if section else len(revised)
    return (revised[:position].rstrip()+'\n\n'+'\n\n'.join(append)+'\n\n'+revised[position:].lstrip()).strip(),info


def context(chapters, items, budget, *, chapter_offset=0):
    """Fit whole record sections only; never silently cut a formula in half."""
    if not items: return '', receipt(items)
    selected, blocks, used = [], [], 0
    def note(count):
        return (f'【核查记录】共{len(items)}段，完整列出{count}段；另有{len(items)-count}段未列入辅助输入。'
            '正文保留全部记录；未核实内容不能当定论，已修订未复核不等于确认仍错。\n')
    # Stable interleaving keeps the ends represented without always favouring
    # the first chapter. Oversized records are explicitly omitted, not guessed.
    order = []
    for index in range((len(items)+1)//2):
        order.append(index)
        if len(items)-1-index != index: order.append(len(items)-1-index)
    reserved = len(note(len(items))) + 2
    for index in order:
        item = items[index]
        label = f"【第{item['chapter']+chapter_offset}部分核查记录】\n"
        cost = len(label) + item['end']-item['start'] + 2
        if used + cost + reserved > budget: continue
        text = chapters[item['chapter']-1][item['start']:item['end']].strip()
        selected.append(index)
        blocks.append((index, label + text))
        used += cost
    text = note(len(selected)) + '\n\n'.join(block for _, block in sorted(blocks))
    if len(text) > budget:
        text = f'【核查记录】共{len(items)}段，均未列入辅助输入，详见原章节；未核实内容不能当定论。'
        selected = []
    if len(text) > budget: raise ValueError('核查记录输入预算不足')
    return text, receipt(items, selected)


def summary_notice(summary, information, language='zh'):
    """Keep a visible boundary even when the summary model ignores cautions."""
    if not information.get('unresolved_sections_total'): return summary
    # Use a label distinct from actual review headings, so finishing twice
    # does not turn this generated notice into another underlying record.
    zh = '**核查提示：**本文仍有待核对记录；总结不表示这些疑点已被排除，具体请对照各部分提示与原文。'
    en = '**Review cautions:** The document still contains items to check. This summary does not resolve them; consult the original text and the cautions in each part.'
    note = en if language == 'en' else zh+'\n\n'+en if language == 'bilingual' else zh
    # Only our exact notice makes the operation idempotent. A model-written
    # label such as "Review cautions: all resolved" cannot bypass this guard.
    if note in summary: return summary
    heading, separator, body = summary.partition('\n')
    return heading + '\n\n' + note + '\n\n' + body.lstrip() if separator else summary
