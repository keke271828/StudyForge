"""Development-only, source-located claim index; not an error detector."""
import hashlib
import json
import re

VERSION='2026-10-15-priority-claim-index-candidate'
PATTERNS={
    'necessity':re.compile(r'别无选择|唯一(?!性)|只有|必须|不可能|必然|总是|任何|所有'),
    'changed_conditions':re.compile(r'不再(?:是|能)|等半径|半径不等|不等半径'),
    'closed_bounds':re.compile(r'闭区间|闭邻域'),
    'equivalence':re.compile(r'当且仅当|等价于|充要|\biff\b|\\iff\b|\\Longleftrightarrow\b'),
    'causality':re.compile(r'导致|造成|平均|显著|因果')}
WEIGHTS={'别无选择':12,'唯一':9,'不再是':10,'不再能':8,'必须':5,'只有':6,
    '等半径':6,'半径不等':8,'不等半径':8,'闭区间':5,'平均':5,'每个':6,'所有':6}


def index(document,limit=2400):
    """Bounded excerpts from original offsets, excluding quotes and code.

    Select diverse claim kinds. Counts are selection evidence, never grades.
    Full source and lecture are still supplied by the normal audit request.
    """
    candidates=[];heading='';fence=None;offset=0;start=None;lines=[]
    def emit(end):
        nonlocal start,lines
        if start is None:return
        text=document[start:end].strip()
        if text and not text.startswith(('>','#')):
            kinds=[key for key,pattern in PATTERNS.items() if pattern.search(text)]
            if kinds:
                weights=[weight for token,weight in WEIGHTS.items() if
                         (re.search(r'唯一(?!性)',text) if token=='唯一' else token in text)]
                score=max(weights,default=0)+3*len(kinds)+(4 if 'changed_conditions' in kinds else 0)
                candidates.append({'start':start,'end':end,'section':heading,'kinds':kinds,'score':score})
        start=None;lines=[]
    for line in document.splitlines(keepends=True):
        stripped=line.strip();marker=re.match(r'^(`{3,}|~{3,})',stripped)
        if fence:
            if marker and marker[1][0]==fence[0] and len(marker[1])>=len(fence):fence=None
            offset+=len(line);continue
        if marker:emit(offset);fence=marker[1];offset+=len(line);continue
        if stripped.startswith('#'):
            emit(offset);heading=stripped.lstrip('# ').strip()[:90];offset+=len(line);continue
        if not stripped:emit(offset);offset+=len(line);continue
        if re.match(r'^(?:[-*] |\d+[.)] )',stripped):emit(offset)
        if start is None:start=offset
        lines.append(line);offset+=len(line)
    emit(len(document))
    ranked=sorted(candidates,key=lambda item:(-item['score'],item['start']))
    selected=[];covered=set()
    # One strong excerpt for each kind first; then fill with remaining claims.
    for key in PATTERNS:
        item=next((item for item in ranked if key in item['kinds'] and item not in selected),None)
        if item:selected.append(item);covered.update(item['kinds'])
    selected.extend(item for item in ranked if item not in selected)
    entries=[]
    for item in selected:
        if len(entries)>=6:break
        before=max(0,item['start']-60);end=min(len(document),item['end']+60)
        if end-before>450:end=before+450
        entry={'section':item['section'],'start':before,'end':end,'text':document[before:end],
            'claim_kinds':item['kinds'],'excerpted':before>0 or end<len(document)}
        trial=entries+[entry]
        if len(json.dumps(trial,ensure_ascii=False))>limit:continue
        entries=trial
    return {'version':VERSION,'document_sha256':hashlib.sha256(document.encode()).hexdigest(),
        'offset_unit':'python_unicode_codepoints','entries':entries,
        'meaning':'priority_index_not_error_verdict','selected':len(entries),'candidates':len(candidates)}


def prompt(document):
    receipt=index(document)
    if not receipt['entries']:return '',receipt
    text=('\n【本机原句定位：优先核对，不是已判定的错误】\n'+json.dumps(receipt,ensure_ascii=False)+
        '\n这些是按措辞找到的候选，完全可能正确；不因入选而报告问题，不要求必须找出错误。'
        '先按原句和上下文核对必要性、等价变形、条件变化和因果归属；需要否定时给出确切依据或符合原假设的反例。'
        '不能把存在一个可用构造写成唯一选择，不能把条件改变后失效的某一步说成整个定理失效。'
        '完整原文和讲解仍在前面，未入选的已写结论、例子和总结同样需要检查。'
        '既有“核查通过”或“局部修正”文字不构成本轮正确性证据。保持原JSON与局部修订规则。')
    return text,receipt
