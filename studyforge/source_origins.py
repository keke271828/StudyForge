"""Keep file-reading method separate from known generation provenance."""
from __future__ import annotations

import json
import re
from collections import Counter

VERSION='2026-10-16-selected-material-origins-v1'
BEGIN='【所选资料身份JSON】\n'
END='\n【资料身份结束】\n'
AI_KINDS=frozenset({'explanation','exercise','solutions','grading','review','image'})
ARTIFACT_ROLES=frozenset({'ai_generated_artifact','derived_source_record','attached_artifact'})
RULES=('所选文件可能是导入资料，也可能是本软件生成的AI成果；按资料身份说明区分。'
    'original_file表示读取文件的方法，不证明作者身份或内容正确。'
    '引用AI成果时称这份讲解、题单或成果，不冒称其为教材原文或已核实证据；'
    '可以讨论和核对其中内容，不因其为AI成果一概否定。未实际读取它引用的教材、网页或旧资料时，不声称已经回查。'
    '来源身份仅在影响归因或结论时点明，不反复声明或打断正常讲解。')
SUMMARY_RULES=('本次输入是已完成的AI讲解、小结及核查意见，不是重新提供的原文件；'
    '提到依据时使用“已提供的讲解”等准确称呼，不能说已经对照原文、查证来源或完成新核查。')


def identify(records):
    result={r['id']:{'role':'provided_material','verification':'not_authenticated'} for r in records}
    registered={r['id']:r.get('project_id') for r in records if r.get('project_id')}
    if not registered:return result
    from .db import many
    ids=list(registered)
    for start in range(0,len(ids),300):
        batch=ids[start:start+300];marks=','.join('?' for _ in batch)
        rows=many('WITH RECURSIVE lineage(root,id,depth) AS ('
            f'SELECT id,id,0 FROM sources WHERE id IN ({marks}) UNION ALL '
            'SELECT l.root,s.original_source_id,l.depth+1 FROM lineage l JOIN source_scopes s ON s.source_id=l.id '
            'WHERE s.original_source_id IS NOT NULL AND l.depth<16) '
            'SELECT l.root,l.id,l.depth,s.project_id,sc.source_id AS scoped,sc.original_source_id AS parent,'
            'a.id AS artifact_id,a.project_id AS artifact_project,a.kind AS artifact_kind '
            'FROM lineage l LEFT JOIN sources s ON s.id=l.id LEFT JOIN source_scopes sc ON sc.source_id=l.id '
            'LEFT JOIN artifact_sources x ON x.source_id=l.id LEFT JOIN artifacts a ON a.id=x.artifact_id '
            'ORDER BY l.root,l.depth',tuple(batch))
        grouped={}
        for row in rows:grouped.setdefault(row['root'],[]).append(row)
        for root,chain in grouped.items():
            owner=registered[root]
            if any((r['project_id'] and r['project_id']!=owner) or
                   (r['artifact_project'] and r['artifact_project']!=owner) for r in chain):
                raise ValueError('资料与成果的项目归属不一致，未读取跨项目内容')
            generated=next((r for r in chain if r['artifact_id']),None)
            if generated:
                kind=generated['artifact_kind']
                role='ai_generated_artifact' if kind in AI_KINDS else 'derived_source_record' if kind=='original' else 'attached_artifact'
                result[root]={'role':role,'artifact_id':generated['artifact_id'],
                    'artifact_kind':generated['artifact_kind'],'via_excerpt':generated['depth']>0,'verification':'not_independently_verified'}
            elif any(r['scoped'] for r in chain):
                missing=any(not r['project_id'] or (r['scoped'] and not r['parent']) for r in chain)
                incomplete=missing or (chain[-1]['depth']==16 and chain[-1]['parent']) or len({r['id'] for r in chain})!=len(chain)
                result[root]={'role':'excerpt_material','lineage':'unresolved' if incomplete else 'provided_material',
                    'verification':'not_authenticated'}
    return result


def header(entries):
    if not entries:return ''
    return BEGIN+json.dumps({'version':VERSION,'materials':entries},ensure_ascii=False,separators=(',',':'))+END


def for_records(records):
    # Existing plain-file transport is unchanged. When generated content is
    # present, list all selected roles so imported material is not conflated.
    if not any(r.get('read_manifest',{}).get('content_origin',{}).get('role') in ARTIFACT_ROLES for r in records):return ''
    names=Counter(r['name'] for r in records)
    return header([{'name':r['name'],'role':r.get('read_manifest',{}).get('content_origin',{}).get('role','provided_material'),
        **({'source_id':r['id']} if names[r['name']]>1 else {}),
        **({'notice':'本软件整理的来源记录，可能含自动识别误差，不等于已重新核对原视频或原资料'}
            if r.get('read_manifest',{}).get('content_origin',{}).get('role')=='derived_source_record' else
           {'notice':'外部附加或类型未知的成果；作者与真实性未认证，不能仅凭附加位置认定AI创作或权威原文'}
            if r.get('read_manifest',{}).get('content_origin',{}).get('role')=='attached_artifact' else {}),
        **({'kind':r['read_manifest']['content_origin']['artifact_kind']}
           if r.get('read_manifest',{}).get('content_origin',{}).get('artifact_kind') else {})} for r in records])


def transport(digest):
    """Recognize only our complete, versioned envelope; never trim unknown data.

    The returned body is for local structural inspection. Callers must keep
    identity metadata on the actual model input and in saved source records.
    """
    if not digest.startswith(BEGIN):return None
    raw,marker,body=digest[len(BEGIN):].partition(END)
    if not marker:return None
    try:data=json.loads(raw)
    except (ValueError,TypeError):return None
    if not isinstance(data,dict) or data.get('version')!=VERSION or not isinstance(data.get('materials'),list):return None
    return data,body


def batches(digest,max_chars,plain_split):
    packet=transport(digest)
    if packet is None:return plain_split(digest,max_chars)
    data,body=packet
    # Attach only identities whose normal source locators occur in this batch.
    # Shrink a transport part if the added registry would exceed the same cap.
    entries=data['materials'];todo=list(reversed(plain_split(body,max_chars)));result=[]
    while todo:
        part=todo.pop();names=set(re.findall(r'\n\[来源 ([^\n｜]+)｜',part))
        relevant=[]
        for entry in entries:
            if not isinstance(entry,dict) or not isinstance(entry.get('name'),str):continue
            if isinstance(entry.get('source_id'),str):
                located=re.search(r'\n\[来源 '+re.escape(entry['name'])+r'｜[^\n]+\] \[资料ID:'+re.escape(entry['source_id'])+r'\]\n',part)
            else:
                located=entry['name'] in names or '\n[来源 '+entry['name']+'｜' in part
            if located:relevant.append(entry)
        prefix=header(relevant)
        if len(prefix)+len(part)<=max_chars:
            result.append(prefix+part);continue
        if max_chars<800:raise ValueError('本次分段预算不足以保留资料身份和正文，请增大分段长度')
        smaller=max(400,min(max_chars-len(prefix),max_chars//2))
        children=plain_split(part,smaller)
        if len(children)==1 and children[0]==part:raise ValueError('无法在本次分段预算内完整保留资料身份')
        todo.extend(reversed(children))
    return result
