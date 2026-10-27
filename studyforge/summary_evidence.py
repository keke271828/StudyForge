"""Use spare summary context for exact body conditions, never a fact verdict."""
from __future__ import annotations

import hashlib
import re

VERSION='2026-10-16-summary-body-evidence-v1'
_CONDITION=re.compile(r'前提|假设|条件|仅当|只有|只在|除非|否则|不保证|不能|不等于|不代表|未必|不意味着|'
    r'不推出|不自动|例外|反例|边界|退化|适用|必要|充分|非零|保持.*?不变|'
    r'\b(?:if|unless|assuming|provided|requires?|necessary|sufficient|only|except|nonzero|boundary)\b|'
    r'\\(?:forall|exists|iff|ne(?:q)?)\b',re.I)
_HEADING=re.compile(r'^#{1,6}\s+(.+?)\s*#*\s*$')


def paragraphs(text):
    """Yield whole non-code/quote blocks, keeping display-math lines together."""
    offset=start=0;fence=None;math=None;skip=False;title=''
    def item(end):
        if skip or end-start>1200:return None
        raw=text[start:end];left=len(raw)-len(raw.lstrip());right=len(raw.rstrip())
        if right<=left:return None
        return {'start':start+left,'end':start+right,'title':title,'text':raw[left:right]}
    for line in text.splitlines(keepends=True):
        value=line.strip();marker=re.match(r'^(`{3,}|~{3,})',value)
        heading=_HEADING.fullmatch(value) if not fence and not math else None
        if heading:
            if block:=item(offset):yield block
            title=heading[1];start=offset+len(line);skip=False
        elif not value and not fence and not math:
            if block:=item(offset):yield block
            start=offset+len(line);skip=False
        else:
            if marker and not math:
                skip=True
                if fence is None:fence=(marker[1][0],len(marker[1]))
                elif marker[1][0]==fence[0] and len(marker[1])>=fence[1]:fence=None
            elif not fence:
                if value.startswith('>') or (line.startswith(('    ','\t')) and not math):skip=True
                if math=='bracket':
                    if r'\]' in line:math=None
                elif math=='dollar':
                    if len(re.findall(r'(?<!\\)\$\$',line))%2:math=None
                elif r'\[' in line and r'\]' not in line:math='bracket'
                elif len(re.findall(r'(?<!\\)\$\$',line))%2:math='dollar'
        offset+=len(line)
    if not fence and not math and (block:=item(len(text))):yield block


def augment(plan,chapters,budget,*,cautions=()):
    """Add bounded exact excerpts only when the old context has spare room.

    Do not evict any old outline, recap or caution, or use omitted chapters.
    The selected AI prose is not an original source or newly checked truth.
    """
    if len(plan['text'])>budget:raise ValueError('已有总结输入超过本次预算，不能静默扩大或裁剪')
    if plan.get('body_evidence',{}).get('version')==VERSION:return dict(plan)
    original=plan['text'];info={'version':VERSION,'included':0,'characters':0,'chapters':[],
        'fragments':[],'meaning':'exact_ai_body_excerpts_not_fact_verification'}
    result=dict(plan,body_evidence=info)
    if not plan.get('excerpted'):
        info['reason']='full_context';return result
    if plan.get('omitted_chapters'):
        info['reason']='chapter_omissions';return result
    allowance=min(3000,budget//8,budget-len(original)-2)
    if allowance<200:
        info['reason']='no_spare_room';return result
    from .teaching import summary_section
    buckets=[]
    for number,chapter in enumerate(chapters,1):
        protected=[(i['start'],i['end']) for i in cautions if i['chapter']==number]
        if section:=summary_section(chapter):protected.append(section)
        choices=[]
        for block in paragraphs(chapter):
            if any(block['start']<end and block['end']>start for start,end in protected):continue
            text=block['text']
            if len(text)>1000 or text in original:continue
            score=min(8,len(_CONDITION.findall(text)))
            if not score:continue
            choices.append(dict(block,chapter=number,score=score))
        buckets.append(sorted(choices,key=lambda b:(-b['score'],b['start']))[:16])
    label=('【辅助：已完成讲解正文中的条件与边界片段】\n'
        '以下逐字节选同一批AI讲解，不是原文件、外部证据或新增审核；其中条件也可能有误。'
        '与小结有冲突时须核对并保留不确定，不自行选一个当定论。字符位置从0开始，右端不包含。\n')
    selected=[];seen=set();used=len(label)
    order=[]
    for i in range((len(buckets)+1)//2):
        order.append(i)
        if len(buckets)-1-i!=i:order.append(len(buckets)-1-i)
    for depth in range(16):
        for index in order:
            if depth>=len(buckets[index]):continue
            block=buckets[index][depth];fingerprint=hashlib.sha256(block['text'].encode()).hexdigest()
            prefix=f"【第{block['chapter']}部分｜{block['title'][:80]}｜字符[{block['start']},{block['end']})】\n"
            snippet=prefix+block['text'];cost=len(snippet)+2
            if fingerprint in seen or used+cost>allowance:continue
            selected.append(snippet);seen.add(fingerprint);used+=cost
            info['fragments'].append({k:block[k] for k in ('chapter','start','end')}|{'sha256':fingerprint})
            if len(selected)==16:break
        if len(selected)==16:break
    if selected:
        addition=label+'\n\n'.join(selected)
        result['text']=original+'\n\n'+addition
        info.update(included=len(selected),characters=len(addition),chapters=sorted({i['chapter'] for i in info['fragments']}),reason='spare_context')
    else:info['reason']='no_fitting_candidate'
    assert len(result['text'])<=budget
    return result
