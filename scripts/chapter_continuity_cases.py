"""Synthetic registered artifacts for chapter scheduling acceptance."""
import re

from studyforge import ai, artifact_sources, source_origins
from studyforge.config import artifacts_dir
from studyforge.db import execute,j,now,one,uid


def seed(project_id,kind):
    if kind=='dependent':
        materials=[('连续推导','# 定义与前提\n设 a、b 为实数。\n'+
            ''.join(f'推导单元{i:04}。' for i in range(700))+'\n结尾条件：每一步仍按给定前提。')]
    else:
        materials=[('独立问题A','本节独立讨论概念A。'*100),
                   ('接上文的证明材料','本节独立讨论概念B，不依赖另一文件。'*70)]
    sources=[]
    for title,body in materials:
        artifact_id=uid();path=artifacts_dir()/(artifact_id+'.txt');path.write_text(body,encoding='utf-8')
        execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)',
            (artifact_id,project_id,'[]','explanation','txt',str(path),title,j({'fixture':True}),now()))
        artifact_sources.sync_project(project_id)
        row=one('SELECT source_id FROM artifact_sources WHERE artifact_id=?',(artifact_id,))
        sources.append(row['source_id'])
    return sources


def split(digest):
    if '连续推导' in digest:
        return ai.explanation_batches(digest,max_chars=5000)
    # Absolute test paths vary. Fit each independent source whole, including
    # identity overhead, without accidentally cutting the second source into
    # the first batch just because one fixture directory has a shorter name.
    packet=source_origins.transport(digest)
    metadata,body=packet
    parts=re.split(r'(?=\n\[来源 )',body)
    preface,originals=parts[0],parts[1:]
    budget=max(len(preface)+len(originals[0]),max(map(len,originals)))+len(source_origins.header(metadata['materials']))+64
    return ai.explanation_batches(digest,max_chars=budget)


def document(part,has_previous):
    return (f'# DRAFT_PART_{part}\n\n这是受控的章节调度验收文本，不用于评价真实教学质量。\n\n'
        f'本次收到前一部分讲解：{"是" if has_previous else "否"}。\n\n'
        '给定实数 $a,b$，$a^2+b^2-2ab=(a-b)^2\\ge0$，等号条件为 $a=b$。\n\n'
        '## 系统性总结\n保留定义、前提及相邻推导的衔接。')
