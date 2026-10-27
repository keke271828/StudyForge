"""Bounded exact references only for repeated paragraphs in a quick review.

The public opening is a locator preview, never an alternate teaching source.
IDs resolve only against the current, unchanged document and registered whole
ordinary paragraphs. No formula normalization or approximate matching occurs.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from .summary_evidence import paragraphs

VERSION = '2026-10-21-review-duplicate-passages-v1'
_REFERENCE = re.compile(r'\[(?:[^\]\n]*[｜|][^\]\n]*|(?:来源|Source)\s*[:：][^\]\n]*)\]', re.I)
_LINK = re.compile(r'\[[^\]\n]*\]\([^\s)]+\)|https?://[^\s<>)\]]+', re.I)
_SCOPE = re.compile(r'只有|必须|唯一|任意|所有|必然|不可能|\b(?:only|must|unique|every|all|always|never)\b',re.I)


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _id(document_hash, start, end):
    return f'p-{document_hash[:12]}-{start:x}-{end:x}'


def eligible(document):
    from .lesson_cautions import records
    protected = records([document])
    for part in paragraphs(document):
        text = part['text']
        if (not 16 <= len(text) <= 1200 or _REFERENCE.search(text) or _LINK.search(text)
                or re.match(r'^\s*(?:\$\$|\\\[)',text)
                or re.search(r'^ {0,3}(?:[-*+]\s|\d+[.)、]\s*|<[/A-Za-z])',text,re.M)
                or '|' in text
                or any(part['start'] < item['end'] and part['end'] > item['start'] for item in protected)):
            continue
        yield part


def build(document, budget=3200, max_entries=24):
    if not 200 <= budget <= 12000 or not 1 <= max_entries <= 64:
        raise ValueError('段落定位预算或数量超限')
    fingerprint = _hash(document)
    available = list(eligible(document))
    counts = Counter(p['text'] for p in available)
    choices = [p for p in available if counts[p['text']] > 1]
    # Extra locator convenience for scope assertions, not an error detector.
    # The complete draft is still audited; all other edits can use literal before.
    grouped={}
    for part in choices:grouped.setdefault(part['text'],[]).append(part)
    ordered=sorted(grouped.values(),key=lambda group:(not bool(_SCOPE.search(group[0]['text'])),group[0]['start']))
    public, locations = [], {}
    for group in ordered:
        if len(group)>8 or len(public)+len(group)>max_entries:continue
        additions=[{'passage_id':_id(fingerprint,part['start'],part['end']),
                    'opening':part['text'][:64], 'opening_is_excerpt':len(part['text'])>64} for part in group]
        if len(json.dumps(public+additions,ensure_ascii=False,separators=(',',':'))) > budget:
            continue
        public.extend(additions)
        for part,item in zip(group,additions):
            locations[item['passage_id']]={k:part[k] for k in ('start','end')}
            locations[item['passage_id']]['sha256']=_hash(part['text'])
    public.sort(key=lambda item:locations[item['passage_id']]['start'])
    receipt={'version':VERSION,'document_sha256':fingerprint,'eligible_passages':len(available),'ambiguous_passages':len(choices),
             'registered_passages':len(public),'unregistered_passages':len(choices)-len(public),
             'locator_characters':len(json.dumps(public,ensure_ascii=False,separators=(',',':'))),
             'coordinate_unit':'unicode_code_points',
             'meaning':'exact_locations_not_error_detection_or_fact_verification',
             'locations':[{'passage_id':item['passage_id'],**locations[item['passage_id']]} for item in public]}
    return {'version':VERSION,'document_sha256':fingerprint,'public':public,'locations':locations,'receipt':receipt}


def validated_locations(document, plan):
    """Reject stale, invented or widened coordinate records as a whole."""
    if (not isinstance(plan,dict) or plan.get('version')!=VERSION
            or plan.get('document_sha256')!=_hash(document)
            or not isinstance(plan.get('locations'),dict) or len(plan['locations'])>64
            or not isinstance(plan.get('public'),list)):
        return {}
    available=list(eligible(document));counts=Counter(p['text'] for p in available)
    allowed={(p['start'],p['end']):p['text'] for p in available if counts[p['text']]>1}
    exposed=[row.get('passage_id') for row in plan['public'] if isinstance(row,dict)]
    if (len(exposed)!=len(plan['public']) or len(exposed)!=len(set(exposed))
            or set(exposed)!=set(plan['locations'])):return {}
    result={}
    registered_counts=Counter()
    for key,location in plan['locations'].items():
        if not isinstance(location,dict):return {}
        start,end=location.get('start'),location.get('end')
        if type(start) is not int or type(end) is not int:return {}
        text=allowed.get((start,end))
        if text is None or key!=_id(plan['document_sha256'],start,end) or location.get('sha256')!=_hash(text):return {}
        result[key]=(start,end)
        registered_counts[text]+=1
    if any(registered_counts[text]!=counts[text] for text in registered_counts):return {}
    return result
