"""Bounded lesson navigation and mechanical provenance checks, without model calls."""
from __future__ import annotations

import re

from .teaching import headings, summary_section

_CITATION = re.compile(r'\[([^\]\n]{1,180}?)｜([^\]\n]{1,300})\]')
_SECONDS = re.compile(r'(约)?(\d+(?:\.\d+)?)(?:[-–—~至](\d+(?:\.\d+)?))?秒(画面)?')


def normalized(value):
    return re.sub(r'\s+', '', value)


def locator_key(value):
    """Accept equivalent line notation, never a part of a larger range.

    A one-line source is equally located by 行1, 行1-1 or 第1行. Quotes still
    require a unique source and verbatim matching at that exact location.
    Decimal timestamps and range separators accept equivalent notation.
    """
    value = normalized(str(value))
    seconds = _SECONDS.fullmatch(value)
    if seconds:
        start = float(seconds[2]); end = float(seconds[3] or seconds[2])
        if end >= start:
            kind = 'frame' if seconds[1] or seconds[4] else 'seconds'
            return f'{kind}:{start:.9g}-{end:.9g}'
    line = re.fullmatch(r'行(\d+)(?:[-–—](\d+))?', value)
    single = re.fullmatch(r'第(\d+)行', value) if not line else None
    if not line and not single: return value
    start = int((line or single)[1])
    end = int(line[2]) if line and line[2] else start
    if start < 1 or end < start: return value
    return f'行{start}' if start == end else f'行{start}-{end}'


def _integer_range(locator):
    value = normalized(str(locator))
    line = re.fullmatch(r'(?:行|第)(\d+)(?:[-–—至](\d+))?(行)?', value)
    page = re.fullmatch(r'第?(\d+)(?:[-–—至](\d+))?页', value)
    match = page or line
    if not match or (line and value.startswith('第') and not line[3]): return None
    start, end = int(match[1]), int(match[2] or match[1])
    if start < 1 or end < start: return None
    return ('page' if page else 'line'), start, end


def _range_text(source, locator):
    """Resolve only coordinates supported by this selected original record."""
    requested = _integer_range(locator)
    if requested:
        kind, first, last = requested
        if last - first > 10000: return None
        positions = {}
        for part in source['segments']:
            span = _integer_range(part['locator'])
            if not span or span[0] != kind or span[2] < first or span[1] > last: continue
            text = str(part.get('text', ''))
            lines = text.splitlines() if kind == 'line' else [text]
            # Never guess a line/page mapping if the parser did not preserve it.
            if len(lines) != span[2] - span[1] + 1: continue
            for number in range(max(first, span[1]), min(last, span[2]) + 1):
                positions.setdefault(number, []).append(lines[number - span[1]])
        if all(len(positions.get(number, [])) == 1 for number in range(first, last + 1)):
            return '\n'.join(positions[number][0] for number in range(first, last + 1))
        return None
    requested = _SECONDS.fullmatch(normalized(str(locator)))
    if not requested: return None
    first, last = float(requested[2]), float(requested[3] or requested[2])
    if last < first: return None
    frames = bool(requested[1] or requested[4])
    selected = []
    for part in source['segments']:
        span = _SECONDS.fullmatch(normalized(str(part['locator'])))
        if not span or bool(span[1] or span[4]) != frames: continue
        start, end = float(span[2]), float(span[3] or span[2])
        if frames and first == last:
            # A rounded, approximate frame must still identify exactly one image.
            precision = len(requested[2].partition('.')[2])
            if abs(start - first) <= .5 * 10 ** -precision + 1e-9:
                selected.append((start, end, str(part.get('text', ''))))
        elif start >= first - 1e-6 and end <= last + 1e-6:
            selected.append((start, end, str(part.get('text', ''))))
    if frames:
        return selected[0][2] if len(selected) == 1 else None
    # A continuous citation can cover multiple ASR sentences; its endpoints
    # must be actual sentence boundaries, not invented or unread positions.
    if (selected and abs(selected[0][0] - first) < 1e-6 and abs(selected[-1][1] - last) < 1e-6):
        return '\n'.join(item[2] for item in selected)
    return None


def outline(records, budget=6000):
    entries = []
    for source in records:
        for part in source['segments']:
            text = str(part.get('text', ''))
            labels = [title for _, _, title in headings(text)]
            if not labels:
                labels = [next((line.strip() for line in text.splitlines() if line.strip()), '(图像或空文本)')]
            for label in labels:
                entries.append({'source_id': source.get('id'), 'name': source['name'], 'locator': str(part['locator']),
                                'label': label[:120], 'excerpt_cut': len(label) > 120})
    count = min(len(entries), max(1, (budget - 300) // 220))
    selected = [entries[i * (len(entries)-1) // (count-1)] for i in range(count)] if count > 1 else entries[:1]
    lines = [f"[{x['name']}｜{x['locator']}] 导航节选：{x['label']}"[:210] for x in selected]
    omitted = len(entries) - len(selected)
    text = ('【全文来源导航】以下为原文标题或开头节选，仅用于安排章节与衔接，不是内容摘要、完整条件或证据。'
            '不得根据导航猜测未提供原文的结论。\n' + '\n'.join(lines) +
            f'\n导航共{len(entries)}项，列出{len(selected)}项，另有{omitted}项未列出；所有原文仍逐部分交给你阅读。')
    return {'text': text, 'entries': len(entries), 'listed': len(selected), 'omitted': omitted}


def chapter_context(navigation, originals, index, chapters, preparation):
    blocks = [navigation['text']]
    if index:
        blocks.append('【上一部分原文末尾，仅供续接分断句子或公式，不重复讲完整上一章】\n' + originals[index-1][-1000:])
        snippets = []
        recent = chapters[-24:]
        per = max(80, 4000 // max(1, len(recent)))
        for number, chapter in enumerate(recent, len(chapters)-len(recent)+1):
            span = summary_section(chapter)
            summary = chapter[span[0]:span[1]] if span else chapter
            snippets.append(f'已写第{number}部分：{summary[:per]}\n[衔接节选，不作为原文证据]')
        if snippets:
            blocks.append('【已写内容衔接，可能含错误；优先核对当前完整原文】\n' + '\n'.join(snippets))
        from . import lesson_cautions
        cautions = lesson_cautions.records(recent)
        if cautions:
            text, _ = lesson_cautions.context(recent, cautions, 1600, chapter_offset=len(chapters)-len(recent))
            blocks.append('【已写部分的核查记录】只在与本部分有关时核对相应条件，不把旧疑点当已证结论，也不为此展开无关章节。\n' + text)
        if len(chapters) > len(recent):
            blocks.append(f'【衔接范围】仅列最近{len(recent)}部分；更早部分及其核查记录未在此次衔接输入中列出，不代表没有疑点。')
    # The caller resolves notes against the actual original slice. A reading
    # part number is not a generation part number: reordering inputs or adding
    # primary library material can change transport boundaries.
    if preparation:
        blocks.append(preparation)
    return '\n\n'.join(blocks)


def chapter_dependencies(originals):
    """Keep mechanically identifiable continuations ordered.

    Other batches receive the complete source slice and source neighbours;
    their drafts are independent, with the full summary assembled afterwards.
    This is a scheduling rule, not an assertion of conceptual independence.
    """
    plan = []
    for index, original in enumerate(originals):
        from .source_origins import transport
        packet=transport(original)
        body=packet[1] if packet is not None else original
        beginning = re.sub(r'^\s*\[来源 [^\n]+\]\s*', '', body)[:400]
        continuation = index > 0 and bool(re.match(
            r'^\s*(?:#{1,6}\s+)?(?:\[原文续接\]|(?:(?:下面|现在|本节|我们)(?:将|来)?\s*)?(?:接(?:上文|上节|前文).{0,12}(?:证明|推导)|继续(?:上文|上一节)的(?:证明|推导)))', beginning))
        plan.append({'index': index, 'after': index - 1 if continuation else None,
                     'reason': '原文在证明、公式或同一段内容中续接，等待前一部分' if continuation else ''})
    return plan


def assemble_chapters(chapters):
    if len(chapters) == 1: return chapters[0]
    result = []
    for index, chapter in enumerate(chapters, 1):
        span = summary_section(chapter)
        replacements = []
        for start, depth, title in headings(chapter):
            end = chapter.find('\n', start)
            if end < 0: end = len(chapter)
            label = f'第{index}部分小结' if span and start == span[0] else title
            level = min(6, depth + (1 if index > 1 else 0))
            replacements.append((start, end, '#' * level + ' ' + label))
        for start, end, value in reversed(replacements): chapter = chapter[:start] + value + chapter[end:]
        result.append(chapter)
    return '\n\n'.join(result)


def visible_text(document):
    lines, fence = [], None
    for line in document.splitlines():
        found = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if found:
            marker = found[1]
            if fence is None: fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence): fence = None
            lines.append(''); continue
        lines.append('' if fence else line)
    return '\n'.join(lines)


def expand_single_source_labels(document, records):
    """Fill a shortened label only when its selected original is unambiguous.

    A model may write [来源｜位置] in a single-source lesson. The software
    knows that source's name, but does not infer missing or unread coordinates,
    choose between sources, edit code examples, or validate the claim itself.
    """
    if len(records) != 1 or re.search(r'[\]\n]', records[0]['name']):
        return document, 0
    count, lines, fence = 0, [], None

    def replace(match):
        nonlocal count
        if match[1].strip() != '来源': return match[0]
        candidate = f"[来源 {records[0]['name']}｜{match[2]}]"
        checks = citation_checks(candidate, records)
        if checks['matched_citations'] != 1: return match[0]
        count += 1
        return candidate

    for line in document.splitlines(keepends=True):
        found = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if found:
            marker = found[1]
            if fence is None: fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence): fence = None
            lines.append(line)
        else:
            lines.append(line if fence else _CITATION.sub(replace, line))
    return ''.join(lines), count


def citation_checks(document, records):
    index = {}
    for source in records:
        for part in source['segments']:
            index.setdefault((normalized(source['name']), locator_key(part['locator'])), []).append(str(part.get('text', '')))
    text = visible_text(document)
    warnings, matched, cited = [], 0, 0
    def candidates(name, locator):
        name = re.sub(r'^来源(?:\s+|[:：]\s*)', '', name.strip())
        exact = index.get((normalized(name), locator_key(locator)), [])
        if exact: return exact
        return [value for source in records if normalized(source['name']) == normalized(name)
                and (value := _range_text(source, locator)) is not None]
    for name, locator in _CITATION.findall(text):
        cited += 1
        options = candidates(name, locator)
        if len(options) == 1: matched += 1
        else: warnings.append(f'[{name}｜{locator}]：' + ('同名来源位置不唯一，需注明具体资料' if options else '来源或位置未匹配所选原文，需核对'))
    quotes, verified, verbatim, whitespace_only, attributed_unverified = 0, 0, 0, 0, 0
    quote_results = []
    lines = text.splitlines()
    position = 0
    def trailing_reference(line):
        value = re.sub(r'^[—–-]+\s*', '', line.strip())
        standard = _CITATION.fullmatch(value)
        if standard: return (standard[1],standard[2]), False
        for source in records:
            for separator in ('，', ','):
                prefix = source['name'] + separator
                if value.startswith(prefix):
                    locator = value[len(prefix):].strip()
                    if (locator and (_integer_range(locator) or _SECONDS.fullmatch(normalized(locator))
                            or any(locator_key(part['locator'])==locator_key(locator) for part in source['segments']))):
                        return (source['name'],locator), True
        return None, False
    def fragments_match(original, fragments):
        offset = 0
        for fragment in fragments:
            offset = original.find(fragment, offset)
            if offset < 0: return False
            offset += len(fragment)
        return bool(fragments)
    while position < len(lines):
        if not re.match(r'^\s*>', lines[position]): position += 1; continue
        start = position
        block = []
        while position < len(lines) and re.match(r'^\s*>', lines[position]):
            block.append(re.sub(r'^\s*> ?', '', lines[position])); position += 1
        references = _CITATION.findall('\n'.join(block))
        body, unbracketed_refs = [], []
        for line in block:
            ref, unbracketed = trailing_reference(line)
            if ref:
                if unbracketed:
                    references.append(ref)
                    unbracketed_refs.append(ref)
            else: body.append(line)
        cursor = position
        while cursor < len(lines) and not lines[cursor].strip(): cursor += 1
        if not references and cursor < len(lines):
            ref, unbracketed = trailing_reference(lines[cursor])
            if ref:
                references = [ref]
                if unbracketed: unbracketed_refs.append(ref)
        for ref in unbracketed_refs:
            cited += 1
            options = candidates(*ref)
            if len(options) == 1: matched += 1
            else: warnings.append(f'[{ref[0]}｜{ref[1]}]：' + ('同名来源位置不唯一，需注明具体资料' if options else '来源或位置未匹配所选原文，需核对'))
        quote = _CITATION.sub('', '\n'.join(body)).strip()
        explicit_original = bool(re.match(r'^原文\s*[:：]', quote))
        quote = re.sub(r'^原文\s*[:：]\s*', '', quote)
        if len(quote)>1 and (quote[0], quote[-1]) in [('“','”'),('「','」'),('"','"')]: quote=quote[1:-1]
        if not quote: continue
        quotes += 1
        options = candidates(*references[0]) if len(references) == 1 else []
        pieces = [x for x in re.split(r'\[\s*(?:…|\.\.\.)\s*\]', quote) if x]
        fragments = [normalized(x) for x in pieces if normalized(x)]
        exact = len(options) == 1 and fragments_match(options[0], pieces)
        found = len(options) == 1 and fragments_match(normalized(options[0]), fragments)
        status = 'verbatim' if exact else 'whitespace_only' if found else 'not_matched' if len(options) == 1 else 'unresolved'
        verbatim += int(exact)
        whitespace_only += int(found and not exact)
        previous_index = start - 1
        while previous_index >= 0 and not lines[previous_index].strip(): previous_index -= 1
        previous = lines[previous_index].strip() if previous_index >= 0 else ''
        claimed = bool(re.search(r'(?:原文|原资料|教材|资料|文中).{0,32}(?:说|写|指出|表述|句|段|如下|这样|原话|引用)|原文[:：]$', previous))
        attributed = bool(references) or explicit_original or claimed
        attributed_unverified += int(attributed and status!='verbatim')
        if len(quote_results) < 50:
            quote_results.append({'quote_index':quotes,'status':status,'attributed':attributed,
                                  'source':references[0][0] if len(references)==1 else None,
                                  'locator':references[0][1] if len(references)==1 else None,
                                  'omitted':len(pieces)>1})
        if found: verified += 1
        else: warnings.append(f'引用块{quotes}：' + ('没有唯一可识别的来源定位，需核对' if len(options)!=1 else
                     '未能在指定位置逐字匹配；可能是改写或格式差异，请对照原文'))
    if not cited: warnings.append('未发现可识别的[来源名｜位置]定位；不能据此确认重要论断已对应原文')
    warnings = list(dict.fromkeys(warnings))
    return {'check_version':'literal-quote-v2', 'citation_count': cited, 'matched_citations': matched, 'quote_count': quotes, 'matched_quotes': verified,
            'verbatim_quotes':verbatim,'whitespace_only_quotes':whitespace_only,'quote_results':quote_results,
            'attributed_unverified_count':attributed_unverified,
            'quote_results_omitted':max(0,quotes-len(quote_results)),
            'warning_count': len(warnings), 'warnings': warnings[:50], 'semantic_verified': False,
            'note': '只核对来源位置与引用片段；旧匹配统计可忽略空白，逐字片段另列。不证明省略恰当、公式等价、论断、证明、覆盖或教学质量正确。'}


def _english_source_warning(warning):
    reasons = {
        '同名来源位置不唯一，需注明具体资料': 'The source name and location are ambiguous; identify the exact material.',
        '来源或位置未匹配所选原文，需核对': 'The source or location did not match the selected original; check the original.',
        '没有唯一可识别的来源定位，需核对': 'A unique source location could not be identified; check the original.',
        '未能在指定位置逐字匹配；可能是改写或格式差异，请对照原文': 'The quote did not match the specified location verbatim; check for paraphrasing or formatting differences.',
        '未发现可识别的[来源名｜位置]定位；不能据此确认重要论断已对应原文': 'No recognizable [source name | location] citations were found; claims have not been linked to the original.',
        '仅忽略空白或换行后匹配，不是逐字确认；空白变化也可能改变公式、代码或词义': 'Matched only after ignoring whitespace or line breaks, not verbatim; whitespace changes may alter formulas, code or meaning.',
        '还有仅忽略空白后匹配的引句，具体条目未逐一列出，请对照原文。': 'More quotations matched only after ignoring whitespace; individual items are not listed. Check the original.'
    }
    if warning in reasons: return reasons[warning]
    heading, separator, reason = warning.rpartition(']：')
    if separator: return heading + ']: ' + reasons.get(reason, 'The source citation needs verification against the original.')
    quote = re.match(r'^引用块(\d+)：(.+)$', warning)
    if quote: return f'Quoted block {quote[1]}: ' + reasons.get(quote[2], 'Verify this quotation against the original.')
    return 'A source location or quotation needs verification against the original.'


def source_warning_text(warning, language='zh'):
    english = _english_source_warning(warning)
    return english if language == 'en' else warning+' / '+english if language == 'bilingual' else warning


def source_notice_messages(checks):
    layout = [f"引用块{row['quote_index']}：仅忽略空白或换行后匹配，不是逐字确认；空白变化也可能改变公式、代码或词义"
              for row in checks.get('quote_results',[]) if row['status']=='whitespace_only']
    if checks.get('whitespace_only_quotes',0)>len(layout):
        layout.append('还有仅忽略空白后匹配的引句，具体条目未逐一列出，请对照原文。')
    return checks['warnings'] + layout


def mark_source_warnings(document, checks, language='zh'):
    if not checks['warning_count'] and not checks.get('whitespace_only_quotes',0): return document
    warnings = source_notice_messages(checks)[:10]
    if language == 'en':
        notes = '\n\n## Source citations requiring verification\n' + '\n'.join('- '+_english_source_warning(x) for x in warnings)
    elif language == 'bilingual':
        notes = '\n\n## 来源定位需核对 / Source citations requiring verification\n' + '\n'.join('- '+x+'\n  '+_english_source_warning(x) for x in warnings)
    else:
        notes = '\n\n## 来源定位需核对\n' + '\n'.join('- '+x for x in warnings)
    notice_count = checks['warning_count'] + checks.get('whitespace_only_quotes',0)
    if notice_count > len(warnings):
        zh = f"另有{notice_count-len(warnings)}项，见成果中的来源核对记录。"
        en = f"There are {notice_count-len(warnings)} more items in the source citation record."
        if checks['warning_count'] > len(checks['warnings']):
            zh += f"记录仅列出前{len(checks['warnings'])}项，其余请对照原文核查。"
            en += f" Only the first {len(checks['warnings'])} items are listed; check the rest against the original."
        notes += '\n- ' + (en if language == 'en' else zh+'\n  '+en if language == 'bilingual' else zh)
    span = summary_section(document)
    if span: return document[:span[0]].rstrip()+notes+'\n\n'+document[span[0]:]
    return document.rstrip()+notes


def annotate_chat_quotes(document, records, language='zh'):
    """Local notice for attributed source quotes; never rewrite their words."""
    if not re.search(r'(?m)^\s*>', document): return document
    checks = citation_checks(document, records)
    selected = [row for row in checks['quote_results'] if row['attributed'] and row['status']!='verbatim']
    if not checks['attributed_unverified_count']: return document
    warnings = []
    for row in selected:
        reason = ('仅忽略空白或换行后匹配，不是逐字确认；空白变化也可能改变公式、代码或词义'
                  if row['status']=='whitespace_only' else
                  '未能在指定位置逐字匹配；可能是改写或格式差异，请对照原文'
                  if row['status']=='not_matched' else '没有唯一可识别的来源定位，需核对')
        warnings.append(f"引用块{row['quote_index']}："+reason)
    title = 'Software quotation check' if language=='en' else '软件引文核对 / Software quotation check' if language=='bilingual' else '软件引文核对'
    note = '\n\n**'+title+'**\n' + '\n'.join('- '+source_warning_text(x,language) for x in warnings[:10])
    remaining = checks['attributed_unverified_count'] - min(10,len(warnings))
    if remaining:
        en = f'{remaining} more attributed quotation blocks require checking; their details are not listed here.'
        zh = f'另有{remaining}处原文引语待核对，未逐一列出；请对照本次所选原文。'
        note += '\n- ' + (en if language=='en' else zh+'\n  '+en if language=='bilingual' else zh)
    return note.strip()+'\n\n'+document
