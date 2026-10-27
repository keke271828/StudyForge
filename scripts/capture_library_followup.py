"""Capture the actual chat-preparation path before/after a quoted follow-up fix."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/library-followup-20261021'
PHASE=sys.argv[1]
assert PHASE in ('baseline','fixed')
target=OUT/PHASE
target.mkdir(parents=True,exist_ok=True)
if (target/'requests.json').exists():raise SystemExit('Do not overwrite saved requests.')
os.environ['STUDYFORGE_DATA_DIR']=str(target/'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(target/'no-local-model')
(target/'data').mkdir(exist_ok=True)
corpus=OUT/'corpus.sqlite3'
if corpus.exists():
    with sqlite3.connect(corpus) as source,sqlite3.connect(target/'data/studyforge.sqlite3') as dest:source.backup(dest)

from studyforge import ai,conversations,library,library_semantic,server
from studyforge.db import create_project,execute,j,now,uid
import pymupdf

SAMPLES=[
 {'name':'math','title':'极限唯一性与邻域半径','mode':'manual','page':9,
  'quote':'极限唯一性证明必须取 ε=(b-a)/2，其他半径都不能得到矛盾。',
  'original':'SOURCE_LIMIT: 设a<b。若同一数列收敛于a和b，对任何ε>0，两条最终邻域条件均成立。'
   '取0<ε≤(b-a)/2即可使两开邻域不相交；取等号是因为边界中点不属于开邻域，代数计算也对称。'
   '也可以取ε=(b-a)/3。分别得N1、N2，取max(N1,N2)后两个条件才对同一个后续n同时成立。'},
 {'name':'gauss','title':'高斯定律的净通量与局部电场','mode':'auto','page':1,
  'quote':'高斯定律中闭合曲面内总电荷为零，所以曲面内部电场处处为零。',
  'original':'SOURCE_GAUSS: 高斯定律的积分形式约束闭合曲面的净通量。总内电荷为零只能推出净通量为零。'
   '场的通量有正负，不能由积分为零推出场在各点为零。举例：均匀场E=E0沿z方向，立方体顶面通量E0A、底面-E0A、侧面0，'
   '总通量0但场非零。外部电荷也能在内部产生场；不能把总净电荷为零当作每一点电荷密度均为零。'},
 {'name':'causal','title':'统计显著与因果识别','mode':'auto','page':2,
  'quote':'调查两万名学生，经常记笔记者成绩显著更好，样本这么大就足以证明多记笔记导致成绩提高。',
  'original':'SOURCE_CAUSAL: 观察性调查比较不同学生，统计显著的成绩差异不能单凭样本量证明记笔记的因果效果。'
   '动机、先前基础与出勤可能同时影响笔记和成绩；可能还有反向因果和抽样选择。大样本主要减少估计的随机误差，'
   '不能消除这些系统偏差。随机分配明确的笔记干预能帮助建立可比组，但结论仍针对具体干预和人群，并需说明效应大小。'}]
QUESTION='这里为什么不成立？请用一个算清楚或说清楚的具体情形解释，只讲这个卡点，不重讲整章，不布置习题。'


def prepare():
    source=OUT/'controlled-book.pdf'
    with pymupdf.open() as pdf:
        for i in range(9):pdf.new_page().insert_text((50,80),'Controlled source page '+str(i+1))
        pdf.save(source)
    b=library.import_book(source,'受控学习参考.pdf')['book'];rows=[]
    for sample in SAMPLES:
        n=library.add_node(b['id'],sample['title']);page=sample['page']
        n=library.update_node(n['id'],{'start_page':1 if sample['name']=='math' else page,'end_page':page,'confirmed':True})
        rid=uid()
        execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (rid,n['id'],library.reading_signature(b,n,'deepseek','controlled-reader','high'),'deepseek','controlled-reader','high','completed','',now(),now()))
        for number in range(n['start_page'],n['end_page']+1):
            raw=sample['original'] if number==page else 'UNRELATED_EARLY_PAGE: An unrelated topic.'
            execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',(rid,number,'PDF 第 '+str(number)+' 页',raw,'',None,None))
        p=create_project('追问对照 '+sample['name']);c=conversations.create(p['id'],'deepseek','deepseek-flash','high')['id']
        mid=uid();text='先前的AI说法，可能错误：\n'+sample['quote'];start=text.index(sample['quote'])
        execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,c,'assistant',text,now()))
        ref={'message_id':mid,'content_sha256':hashlib.sha256(text.encode()).hexdigest(),
             'selection':{'start':start,'end':start+len(sample['quote']),'text':sample['quote']}}
        library.set_preferences(c,p['id'],sample['mode'],[{'node_id':n['id'],'purpose':'reference'}] if sample['mode']=='manual' else [])
        rows.append(dict(sample,project_id=p['id'],conversation_id=c,node_id=n['id'],reply_reference=ref))
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False,'model_concurrency':2})
    library_semantic.set_enabled(False)
    (OUT/'case.json').write_text(j({'question':QUESTION,'cases':rows}),encoding='utf-8')
    with sqlite3.connect(target/'data/studyforge.sqlite3') as db,sqlite3.connect(corpus) as copy:db.backup(copy)


async def main():
    if not corpus.exists():prepare()
    data=json.loads((OUT/'case.json').read_text(encoding='utf-8'));rows=[]
    ai.get_secret=lambda *a:'controlled-fixture-key'
    server.discussion_completed=lambda *a:None
    server.profile_context=lambda *a,**kw:''
    class Capture:
        model='deepseek-flash';effort='high'
        async def agent_stream(self,messages,**kwargs):self.messages=messages;yield 'delta','受控占位回答，不用于教学质量评价。'
        async def close(self):pass
    for sample in data['cases']:
        client=Capture();server.DeepSeekClient=lambda *a,**kw:client
        response=await server._chat_response(server.ChatIn(project_id=sample['project_id'],conversation_id=sample['conversation_id'],
            source_ids=[],text=data['question'],reply_reference=sample['reply_reference'],provider='deepseek',model='deepseek-flash',
            reasoning_effort='high',learning_mode='deep',explanation_style='balanced'))
        raw=''.join([part.decode() if isinstance(part,bytes) else part async for part in response.body_iterator])
        events=[json.loads(line) for line in raw.splitlines() if line]
        assert not [e for e in events if e['type']=='error'],events
        receipt=next((e['value']['receipt'] for e in events if e['type']=='library'),None)
        rows.append({'name':sample['name'],'question':data['question'],'quote':sample['quote'],'original':sample['original'],
                     'messages':client.messages,'receipt':receipt,'original_reached_model':sample['original'] in j(client.messages)})
    (target/'requests.json').write_text(j(rows),encoding='utf-8')
    print(j({'phase':PHASE,'requests':len(rows),'original_reached':[r['original_reached_model'] for r in rows],'external_requests':0}),flush=True)


if __name__=='__main__':asyncio.run(main())
