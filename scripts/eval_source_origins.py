"""Bounded same-model comparisons of selected-file provenance and summaries."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


async def main(name):
    out=ROOT/'build'/name
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai,artifact_sources
    from studyforge.config import artifacts_dir
    from studyforge.db import create_project,execute,j,now,one,uid
    from studyforge.materials import read_original_sources
    from studyforge.source_origins import RULES
    from studyforge.teaching import finish_explanation
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':False,'agent_network_enabled':False,
        'background_learning_enabled':False,'model_concurrency':2})
    project=create_project('资料身份真实对照')
    cases=[]
    class Capture:
        async def complete(self,system,user,**kwargs):
            self.request={'system':system,'user':user}
            return '## 系统性总结\n受控捕获，不是对照结果。'
    # Same summary user message and model as the previous recorded sample.
    prior=ROOT/'build/summary-body-evidence-20261016-1/causal-with_body-records.json'
    old=json.loads(prior.read_text(encoding='utf-8'))[0]
    capture=Capture()
    await finish_explanation(capture,'已完成的AI讲解',summary_plan={'text':old['user']},explanation_style='balanced')
    assert old['user']==capture.request['user']
    cases.append({'name':'summary','title':'总结输入是AI讲解，不是重读原文',
        'question':'只总结已经提供的讲解，保留随机提醒、实际行为与假设实验的身份。',
        'source':old['user'],'requests':{'baseline':{k:old[k] for k in ('system','user')},'with_origin':capture.request}})

    def add(text,name,generated):
        if generated:
            path=artifacts_dir()/name;path.write_text(text,encoding='utf-8');aid=uid()
            execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)',
                (aid,project['id'],'[]','explanation','txt',str(path),name.removesuffix('.txt'),'{}',now()))
            artifact_sources.sync_project(project['id'])
            return one('SELECT s.* FROM sources s JOIN artifact_sources x ON x.source_id=s.id WHERE x.artifact_id=?',(aid,))
        path=out/name;path.write_text(text,encoding='utf-8');sid=uid()
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (sid,project['id'],name,'.txt',str(path),'[]','ready',now()))
        return one('SELECT * FROM sources WHERE id=?',(sid,))

    fixture_cases=[
        ('generated','再次引用生成成果',[
            ('阅读与成绩的讲解.txt',True,'# 阅读与成绩\n讲解称：某教材第12页给出一个随机实验，要求实验组每天额外阅读20分钟，对照组维持常规。期末实验组平均高3分，因此增加阅读有利于这次实验中的成绩。这里没有附上该教材第12页或实验报告。')],
            '请把这份资料中的结论和适用范围讲清楚，并说明为什么不能简单说所有人多阅读都会提高3分。这次只讲解，不出题。'),
        ('mixed','导入片段与生成成果冲突',[
            ('用户提供的实验片段.txt',False,'# 假设实验\n这是一个假设例子。随机分配的是记笔记提醒，不是记笔记行为。提醒组平均高3分；没有排除提醒改变学习投入等其他路径，也没有保证实际记笔记。不能直接估计记笔记本身的效果。'),
            ('提醒实验的旧讲解.txt',True,'# 提醒实验\n这是一份已经完成的讲解。该实验已经证明，多记笔记让成绩提高3分；随机提醒与随机记笔记可以视为同一件事。')],
            '两份材料都在这里，请判断“多记笔记使成绩提高3分”是否已经得到支持，解释核心逻辑，标明你在依据哪份材料。不要布置习题。'),
        ('plain','普通导入资料的讲解对照',[
            ('极限唯一性片段.txt',False,'# 极限唯一性\n若数列同时收敛于a和b，且a<b，取ε=(b-a)/2>0。由极限定义分别得到门槛N1、N2。n>max(N1,N2)时，同时有|x_n-a|<ε、|x_n-b|<ε，因而x_n<(a+b)/2且x_n>(a+b)/2，矛盾。')],
            '我不懂为什么可以取ε=(b-a)/2，以及为什么还要取max(N1,N2)。请把思路讲清楚，用直观但准确的方式解释，不要重新讲整章，也不要出题。'),
    ]
    for case,title,files,question in fixture_cases:
        rows=[add(text,name,generated) for name,generated,text in files]
        records=read_original_sources(rows)
        digest,_=ai._assemble_source_digest(records,records,False)
        capture=Capture()
        await ai.generate_explanation(capture,digest,3,[],style='balanced',requirements=question,learning_mode='deep')
        candidate=dict(capture.request)
        plain_records=[dict(row,read_manifest={k:v for k,v in row['read_manifest'].items() if k!='content_origin'}) for row in records]
        old_digest,_=ai._assemble_source_digest(plain_records,plain_records,False)
        assert candidate['system'].count(RULES)==1
        baseline={'system':candidate['system'].replace(RULES,'')
            .replace('完整阅读所选资料','完整阅读原资料')
            .replace('下方资料内容由软件直接读取所选文件提供，并非界面摘要；不重复工具读取已完整提供的文字。',
                     '下方原资料全文由软件直接读取原文件提供，不是界面摘要；不重复工具读取已完整提供的文字。'),
            'user':candidate['user'].replace(digest,old_digest,1).replace('\n所选资料内容：\n','\n原资料全文：\n',1)}
        cases.append({'name':case,'title':title,'question':question,
            'source':'\n\n'.join(name+'（'+('本软件AI成果' if generated else '导入资料，未认证作者或真实性')+'）\n'+text for name,generated,text in files),
            'read_manifests':[r['read_manifest'] for r in records],
            'requests':{'baseline':baseline,'with_origin':candidate}})
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
    cls=traced_class();results=[]
    for index,case in enumerate(cases):
        async def sample(arm):
            request=case['requests'][arm];native=cls('deepseek-flash',effort='high');start=time.perf_counter()
            row={'case':case['name'],'arm':arm,'model':'deepseek-flash','effort':'high'}
            try:
                answer=''
                async with asyncio.timeout(240):
                    async for kind,value in native.agent_stream([{'role':'system','content':request['system']},{'role':'user','content':request['user']}]):
                        if kind=='final':answer=value
                assert answer.strip(),'Empty final answer'
                file=case['name']+'-'+arm+'-final.md';(out/file).write_text(answer,encoding='utf-8')
                row.update(status='completed',answer_file=file,answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
            except Exception as exc:row.update(status='failed',error_type=type(exc).__name__)
            finally:await native.close()
            row.update(seconds=time.perf_counter()-start,model_requests=len(native.traces),
                http_attempts=[t.public() for t in native.traces],input_characters=len(request['system'])+len(request['user']))
            results.append(row);(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:row[k] for k in ('case','arm','status','seconds','model_requests')},ensure_ascii=True),flush=True)
        order=['baseline','with_origin'] if index%2==0 else ['with_origin','baseline']
        await asyncio.gather(*(sample(arm) for arm in order))


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
