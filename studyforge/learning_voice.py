"""Conservative attribution for explicitly delimited chat evidence.

Unmarked prose is unchanged. Quotations and code are context unless the user
explicitly labels the section as their own work. This is not a prose authorship
detector, and it must never infer that an excluded passage is wrong.
"""
from __future__ import annotations

import re

VERSION = 2
_SOURCE = re.compile(r'^(?:原文|原题|题干|教材(?:原文|摘录|内容)?|参考(?:答案|解析|解答)|'
    r'AI(?:回答|讲解|原话)|导师(?:回答|讲解|原话)|网页(?:回答|原文|内容)|'
    r'引用(?:内容|原文)?|source|question|reference answer|AI answer)\s*[:：]',re.I)
_OWN = re.compile(r'^(?:(?:下面是|这是)?我的(?:理解|问题|疑问|推理|推导|证明|解法|作答|答案|代码|想法|看法)|'
    r'我写的(?:代码|证明|解法)|我自己的(?:理解|推理|代码)|my (?:question|understanding|answer|code|reasoning))'
    r'\s*(?:如下|是)?\s*[:：]',re.I)
_INLINE = re.compile(r'(?:教材(?:原文)?|原文|原题|题干|AI(?:回答|讲解)?|导师|网页)(?:里|中)?'
    r'(?:(?:说|写道|声称|回答)\s*[:：]?|\s*[:：])\s*(?:“[^”\n]*”|「[^」\n]*」|"[^"\n]*")',re.I)
_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')


def partition(text: str) -> tuple[str,str]:
    """Return own/unknown prose and explicitly quoted context, without guessing.

    Keep blank separators, so removing a quoted block never joins words from
    opposite sides into invented evidence. Explicit own-work labels also allow
    a student's self-quoted reasoning and fenced programming examples.
    """
    if not isinstance(text,str):return '', ''
    own,external=[],[]
    mode='neutral';fence=None;fence_own=False;own_started=False
    for line in text.splitlines():
        match=_FENCE.match(line)
        if fence:
            if match and match[1][0]==fence[0] and len(match[1])>=len(fence) and not match[2].strip():
                fence=None;mode='neutral';own.append('');external.append('');continue
            (own if fence_own else external).append(line)
            if not fence_own:own.append('')
            continue
        if match:
            fence=match[1];fence_own=mode=='own';own.append('');external.append('');continue
        if not line.strip():
            own.append('');external.append('')
            if mode=='own' and own_started:mode='neutral'
            continue
        quote=re.match(r'^\s{0,3}>\s?(.*)$',line)
        body=quote[1] if quote else line
        label=re.sub(r'^(?:\s*#{1,6}\s+)?\s*','',body).replace('**','').strip()
        if _SOURCE.match(label):mode='source'
        elif not quote and (owned:=_OWN.match(label)):
            mode='own';own_started=bool(label[owned.end():].strip())
        elif mode=='own':own_started=True
        if (quote and mode!='own') or mode=='source':
            # A closed inline quotation can be followed by the student's own
            # question on the same line. Do not discard that suffix.
            matches=list(_INLINE.finditer(body)) if not quote else []
            if matches:
                remaining=_INLINE.sub('',body)
                external.extend(m[0] for m in matches)
                own.append(remaining);mode='neutral'
            else:external.append(body);own.append('')
        else:
            matches=list(_INLINE.finditer(body))
            external.extend(m[0] for m in matches)
            own.append(_INLINE.sub('',body))
    return '\n'.join(own), '\n'.join(external)


def external_quote(quote: str, text: str) -> bool:
    """Only mark an old insight when the attribution is directly observable."""
    own,external=partition(text)
    return bool(quote and quote in external and quote not in own)
