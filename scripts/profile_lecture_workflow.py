"""One bounded, real lecture workflow on a synthetic ten-page PDF.

Isolated data, source/model timings and provider counts; never save reasoning.
The final lesson is QA material, not a learner's pending worksheet.
"""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
PAGES=[
('数列收敛的定义','设 x_n 是实数数列。x_n 收敛到 a 的意思是：对于任意 ε>0，存在正整数 N，使得每个 n>N 都有 |x_n-a|<ε。N 可以依赖 ε，但不能依赖某一个 n。定义控制的是数列的尾部，不要求前面有限多项也在邻域内。'),
('任意与存在的次序','先给定任意正数 ε，再选择能用于整个尾部的 N。ε 可以很大也可以很小；定义成立时，证明者可选择一个对当前问题有用的特定正数来使用定义。这不能反过来变成只验证一个 ε 就能证明收敛。'),
('开邻域的含义','|x-a|<ε 等价于 a-ε<x<a+ε，是不包含端点的开区间。等号能否成立要看具体不等式的严格性。一个数不可能同时严格大于和严格小于同一个数；落在区间端点和落在区间内部不同。'),
('唯一性证明的目标','要证明同一个实数数列不可能有两个不同极限。可以假设它既收敛到 a 又收敛到 b，且 a<b，从两次定义得到对同一尾项的约束，找到矛盾。证明唯一性也可用其他方法，不要把反证法说成唯一可行路线。'),
('怎样构造半径','令 d=b-a>0，希望围绕 a 与 b 的两个开邻域没有公共点。等半径时，只要 0<ε≤d/2 就满足。取 ε=d/2，两个开区间的相邻端点同为中点 (a+b)/2，但该中点不属于这两个区间，所以它们仍无交集。'),
('分别应用定义','由 x_n→a，对 ε=(b-a)/2 存在 N_1，n>N_1 时 x_n<a+ε=(a+b)/2。由 x_n→b，对同一 ε 存在 N_2，n>N_2 时 x_n>b-ε=(a+b)/2。两次定义各自得到一个门槛，还要使两条约束同时成立。'),
('统一尾部并得到矛盾','取 N=max(N_1,N_2)。当 n>N 时，两条不等式同时成立，于是同一个 x_n 必须同时小于和大于 (a+b)/2。这不可能，故两个不同极限的假设不成立。不能误写成对所有 n 都有这两条约束。'),
('其他半径与方法','取 ε=d/3 也能得到两个互不相交的开邻域，不要求两条估计的边界必须恰好相等。也可用三角不等式 d≤|a-x_n|+|x_n-b|<2ε≤d 得到矛盾。半径取一半便于写成共同中点，便利不等于必要。'),
('检验边界和表示','如果把邻域改成闭区间且半径等于 d/2，两个闭区间在中点相交，就不能照搬开区间的论证。若两侧半径不同为 r_1,r_2，分界点一般不是中点；需要针对实际半径重新检查不相交条件，不能照搬对称计算。'),
('方法总结与范围','本资料仅讨论实数数列极限唯一性，主线是利用任意正 ε 的自由选择，构造不能同时满足的两个尾部约束，再统一门槛。几何说明、代数展开和量词次序需要互相对应。相关延伸必须明确标注，并说明条件；本文未讨论复数、拓扑空间或函数极限。')]


async def main(name):
    folder=ROOT/'build'/name
    if folder.exists() and any(folder.iterdir()):raise SystemExit('Use a fresh folder; keep prior measurements, including setup failures.')
    folder.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    import fitz
    from studyforge import ai,server,conversations
    from studyforge.db import create_job,create_project,execute,j,many,now,one,uid,unj,update_job
    from studyforge.scheduling import execution_scope
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode':'direct','model_concurrency':2,'task_parallel_enabled':True,
        'agent_tools_enabled':False,'agent_network_enabled':False,'background_learning_enabled':False,
        'generation_parallel':False})
    pdf=folder/'十页合成数学原资料.pdf'
    with fitz.open() as doc:
        for index,(title,text) in enumerate(PAGES):
            page=doc.new_page();page.insert_text((48,65),f'{index+1}. {title}',fontname='china-s',fontsize=16)
            assert page.insert_textbox((48,105,545,730),text,fontname='china-s',fontsize=13,lineheight=1.8)>=0
        doc.save(pdf)
    project=create_project('十页数学讲解工作流计时');sid=uid()
    chat=conversations.create(project['id'],'deepseek','deepseek-flash')
    conversations.update(chat['id'],project['id'],{'reasoning_effort':'high'})
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (sid,project['id'],pdf.name,'.pdf',str(pdf),'[]','ready',now()))
    cls=traced_class();clients=[];phases=[]
    class Client(cls):
        def __init__(self,*a,**kw):super().__init__(*a,**kw);clients.append(self)
        def fork(self):return Client(self.model,self.agent_runtime.fork() if self.agent_runtime else None,
            copy.deepcopy(self.conversation),effort=self.effort,vision_model=self._vision_model)
    server.client_for=lambda provider,model=None,effort=None,agent_runtime=None,conversation=None,**kw:Client(
        model,agent_runtime,conversation,effort=effort)
    for function in ('generation_input_records','source_digest','generate_explanation','review_explanation','finish_explanation'):
        original=getattr(server,function)
        def wrap(name,operation):
            async def measured(*a,**kw):
                start=time.perf_counter()
                try:return await operation(*a,**kw)
                finally:phases.append({'name':name,'seconds':time.perf_counter()-start})
            return measured
        setattr(server,function,wrap(function,original))
    value=server.GenerateIn(project_id=project['id'],conversation_id=chat['id'],source_ids=[sid],provider='deepseek',model='deepseek-flash',
        reasoning_effort='high',format='docx',summary_level=3,review_mode='fast',learning_mode='deep',
        explanation_style='balanced',exercises=False,parallel=False,instructions=
        '只围绕这十页原文讲清极限唯一性的证明，说明如何想到取半径和统一门槛；重点讲透方法动机与边界，用一个具体数值例子帮助理解，不布置习题。')
    # Match the API's frozen dialogue semantics; legacy jobs can inherit a
    # null/default conversation effort instead of the value passed here.
    snapshot=server.mentor_snapshot(value)
    snapshot['mentor'].update(model=value.model,reasoning_effort=value.reasoning_effort)
    job=create_job(project['id'],'generate',value.model_dump()|{'dialogue_snapshot':snapshot})
    files=('studyforge/server.py','studyforge/ai.py','studyforge/materials.py','studyforge/document_render.py',
           'studyforge/exporters.py','studyforge/review.py','studyforge/teaching.py')
    (folder/'source-hashes.json').write_text(j({file:hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in files}),encoding='utf-8')
    start=time.perf_counter()
    probe_error=None
    try:
        async with execution_scope(job_id=job,project_id=project['id'],label='首次讲解计时'):
            await asyncio.wait_for(server._generate_job(job,value),420)
    except BaseException as exc:
        probe_error=type(exc).__name__
        update_job(job,'cancelled',0,{'stage':'开发计时已停止'},error=probe_error)
    finally:await asyncio.gather(*(client.close() for client in clients),return_exceptions=True)
    row=one('SELECT status,error FROM jobs WHERE id=?',(job,));artifacts=many('SELECT id,title,path,metadata_json FROM artifacts')
    traces=[trace.public() for client in clients for trace in client.traces]
    result={'status':row['status'],'error':row['error'],'job_id':job,'wall_seconds':time.perf_counter()-start,'phases':phases,
        'requests':len(traces),'traces':traces,'spans':many('SELECT resource,label,status,duration_ms FROM execution_spans WHERE job_id=?',(job,)),
        'artifacts':[{'title':a['title'],'path':a['path']} for a in artifacts],'input_pdf_pages':10,
        'pdf_type':'synthetic_text_pdf_not_scanned','production_data_written':False,'reasoning_saved':False,
        'probe_error':probe_error,'requested_effort':'high','frozen_dialogue':True}
    if artifacts:
        meta=unj(artifacts[0]['metadata_json']);result['source_reading']=meta.get('source_reading');result['lesson_quality']=meta.get('lesson_quality')
    (folder/'result.json').write_text(j(result),encoding='utf-8')
    print(json.dumps({'status':row['status'],'wall_seconds':result['wall_seconds'],'requests':len(traces),'phases':phases},ensure_ascii=True))


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
