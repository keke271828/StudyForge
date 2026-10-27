"""Real-model component comparison for a reproduced note/slice mismatch.

Synthetic, explicit teaching materials; native DeepSeek streaming, no external
tools or private reasoning storage. Four actual reading requests and four draft
requests, isolated from the user's data. This is not a full-book quality score.
"""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {'id':'cauchy','title':'柯西证明：单点非负与恒非负的区别',
     'other':'原文甲：给定二次函数g(t)=t²-4。g(3)=5≥0，但g(0)=-4<0。单点非负不能推出对每个实数非负；这个例子没有平方和结构，也没有断言g(t)恒非负。',
     'original':'原文乙：对实数a_i、b_i，定义f(t)=Σ(a_i t+b_i)²。每一项都是实数平方，所以对每个实数t都有f(t)≥0。记A=Σa_i²，B=Σa_i b_i，C=Σb_i²，展开得f(t)=At²+2Bt+C。A>0时可用最小值或判别式推出B²≤AC；A=0时全部a_i=0，B=0，结论直接成立。',
     'question':'请讲懂乙资料：我直接取t=1也能展开出A、B、C，为什么还不够，为什么要让t可调？请用一个具体数值对照说明单点信息与所有t非负的差别，然后接回证明。不布置习题，最后总结。',
     'checks':['不把g(t)的反例性质赋给f(t)','解释t=1只得到A+2B+C≥0','说明可调参数如何得到更强约束','A=0退化情形不被除法掩盖','例子与符号条件正确，关键动机不跳步']},
    {'id':'gauss','title':'高斯定律：不要把导体空腔条件搬入一般曲面',
     'other':'原文甲：在静电平衡导体中，完全封闭、无内部电荷的空腔，其边界是等势面。利用静电势的唯一性定理，可得空腔内电势常量，电场为零；该结论使用导体静电平衡和封闭无电荷空腔等条件，不能只凭净电荷为零推出。',
     'original':'原文乙：高斯定律∮_S E·dS=Q内/ε0。一般闭合曲面内总电荷Q内=0，只能推出净电通量为0，不能推出曲面内电场处处为0。外部点电荷仍会在内部产生电场，穿入和穿出的有符号通量相互抵消。均匀电场E=E0 z方向，穿过无内部电荷的长方体时，上下面通量相反、四侧面通量为0；若E0≠0，内部场非零。本节未假设闭合曲面是导体空腔。',
     'question':'请讲懂乙资料：总电荷为0为什么不能推出内部电场处处为0？我卡在左边那个积分究竟约束了什么。用均匀电场穿过长方体的具体计算讲清，再说明结论的边界。只讲解，不布置习题，最后总结。',
     'checks':['总电荷零与局部无电荷区分','净通量与点上的矢量场区分','同一长方体穿入穿出的符号和面积正确','不引入未给定的导体条件作为一般结论','具体积分计算帮助当前卡点，不扩成无关课程']},
]


async def main(name):
    out=ROOT/'build'/name
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Use a fresh folder; preserve previous evidence.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai,learning,lesson_quality
    from studyforge.reading_notes import context
    from studyforge.db import j
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':False,'agent_network_enabled':False,
                      'background_learning_enabled':False,'library_reference_mode':'off','model_concurrency':2})
    cls=traced_class();results=[];packets=[]
    async def ask(client,system,user):
        answer=''
        async with asyncio.timeout(300):
            async for kind,value in client.agent_stream([{'role':'system','content':system},{'role':'user','content':user}]):
                if kind=='final':answer=value
        if not answer.strip():raise RuntimeError('Model did not finish a public answer')
        return answer
    async def prepare(case):
        originals=[f'[来源 甲资料.txt｜行1]\n{case["other"]}',f'[来源 乙资料.txt｜行1]\n{case["original"]}']
        read_requests=[];client=cls('deepseek-flash',effort='high')
        class Reading:
            async def complete(self,system,user):
                read_requests.append({'system':system,'user':user})
                return await ask(client,system,user)
        # The real reader remains sequential; only transport slices are provided
        # explicitly for this small reproducible reordering scenario.
        saved=learning.explanation_batches
        learning.explanation_batches=lambda digest:originals
        started=time.perf_counter()
        try:
            notes=await learning.understand_material(Reading(),'unused transport',lambda *args:None)
        finally:
            learning.explanation_batches=saved
            await client.close()
        assert len(notes)==2 and len(client.traces)==2
        for entry,request in zip(notes,read_requests):
            request['final_note']=entry['text'];request['saved_input_scope']=entry['input_scope']
        (out/(case['id']+'-reading.json')).write_text(j({'requests':read_requests,'seconds':time.perf_counter()-started,
            'http_attempts':[t.public() for t in client.traces]}),encoding='utf-8')
        original=originals[1]
        records=[{'name':'乙资料.txt','segments':[{'locator':'行1','text':case['original']}]},
                 {'name':'甲资料.txt','segments':[{'locator':'行1','text':case['other']}]}]
        navigation=lesson_quality.outline(records)
        legacy=learning.reading_context(notes)
        # Exactly the old index-0 selector, after the target moved from read
        # part 2 to write part 1. Preserve this known defect only in the probe.
        old=legacy.split('[阅读笔记 2]',1)[0][:3000]
        old=navigation['text']+'\n\n【本部分相关阅读笔记，仅辅助安排，不替代原文；超过3000字时为节选】\n'+old
        new,receipt=context(notes,original)
        new=lesson_quality.chapter_context(navigation,[original,originals[0]],0,[],new)
        assert receipt['matched_notes']==1 and receipt['included'][0]['reading_part']==2
        requests={}
        for arm,preparation in [('baseline',old),('candidate',new)]:
            captured=[]
            class Capture:
                async def complete(self,system,user,**kwargs):
                    captured.append([{'role':'system','content':system},{'role':'user','content':user}])
                    return 'Capture only'
            await ai.generate_explanation(Capture(),original,3,[],style='balanced',learning_mode='deep',
                requirements=case['question'],preparation=preparation,
                section='这是本次讲解第1/2部分；解释当前完整原文，本部分小结稍后可参与全文总结。')
            requests[arm]=captured[0]
        assert requests['baseline'][0]==requests['candidate'][0]
        packets.append(case|{'reading_notes':notes,'receipt':receipt,'requests':requests,
            'scenario':'synthetic materials; target read part 2 is now generation part 1',
            'reading_requests':2,'reading_seconds':time.perf_counter()-started})
        (out/'inputs.json').write_text(j({'cases':packets,'planned_requests':8,'tools':False,'history':False,
            'production_data_modified':False,'model':'deepseek-flash','effort':'high'}),encoding='utf-8')
    # Avoid a global monkeypatch race between the two small preparations.
    for case in CASES:await prepare(case)
    for number,case in enumerate(packets):
        async def sample(arm):
            client=cls('deepseek-flash',effort='high');started=time.perf_counter()
            row={'case':case['id'],'arm':arm}
            try:
                request=case['requests'][arm]
                answer=await ask(client,request[0]['content'],request[1]['content'])
                path=out/(case['id']+'-'+arm+'-final.md');path.write_text(answer,encoding='utf-8')
                row.update(status='completed',answer_file=path.name,characters=len(answer),
                           answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
            except Exception as exc:
                row.update(status='failed',error_type=type(exc).__name__)
            finally:await client.close()
            row.update(seconds=time.perf_counter()-started,model_requests=len(client.traces),
                http_attempts=[t.public() for t in client.traces],
                input_characters=sum(len(m['content']) for m in case['requests'][arm]))
            results.append(row);(out/'results.json').write_text(j(results),encoding='utf-8')
            print(json.dumps({k:row[k] for k in ('case','arm','status','seconds','model_requests')}),flush=True)
        order=('baseline','candidate') if number%2==0 else ('candidate','baseline')
        await asyncio.gather(*(sample(arm) for arm in order))


if __name__=='__main__':
    asyncio.run(main(sys.argv[1]))
