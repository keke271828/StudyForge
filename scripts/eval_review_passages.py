"""Compare actual quick-review delivery for two saved, imperfect model drafts.

Run baseline before the change, then registered after it. Isolated data, native
provider protocol, no tools or hidden reasoning persistence. The same original
draft remains frozen for both phases; applying a patch is not proof of accuracy.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


async def main(name,phase,duplicate_only=False):
    out=ROOT/'build'/name
    out.mkdir(parents=True,exist_ok=True)
    if (out/(phase+'-results.json')).exists():raise SystemExit('Preserve the previous phase.')
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai
    from studyforge.review import review_explanation
    from studyforge.exporters import export_docx
    from studyforge.db import j
    from scripts.diagnose_deepseek_speed import traced_class
    if phase=='baseline':
        # For the new duplicate-only case, reproduce the old request exactly
        # by omitting the optional locator input. No production setting changes.
        import studyforge.review_passages as passages
        original_build=passages.build
        def without_registry(document):
            plan=original_build(document);plan['public']=[];plan['locations']={};return plan
        passages.build=without_registry
    ai.save_settings({'api_connection_mode':'direct','background_learning_enabled':False,
        'agent_tools_enabled':False,'agent_network_enabled':False,'library_reference_mode':'off','model_concurrency':2})
    if not (out/'inputs.json').exists():
        old=ROOT/'build/lecture-progression-real-20261018-1'
        rate=next(c for c in json.loads((old/'inputs.json').read_text(encoding='utf-8'))['cases'] if c['id']=='rate_units')
        new=ROOT/'build/reading-note-real-20261021-1'
        gauss=next(c for c in json.loads((new/'inputs.json').read_text(encoding='utf-8'))['cases'] if c['id']=='gauss')
        cases=[{'id':'gauss','title':'高斯定律：额外零场条件与总结','source':'[来源 乙资料.txt｜行1]\n'+gauss['original'],
            'requirements':gauss['question'],'draft':(new/'gauss-candidate-final.md').read_text(encoding='utf-8'),
            'checks':['保留长方体通量与局部电场解释','核查区域、全空间、边界与静电条件的范围','充分条件不能变成指定必要条件']},
            {'id':'rate','title':'速率模型：过量物质与反应级数','source':'[来源 样例.txt｜行1]\n'+rate['source'],
            'requirements':rate['question'],'draft':(old/'rate_units-candidate-final.md').read_text(encoding='utf-8'),
            'checks':['保留单位推导和0.03计算','B近似固定不是B反应级数变成0','反应式、实验速率律、基元条件的范围','原文没有给定的时间变化不写成无条件事实']}]
        if duplicate_only:
            repeated='为了让两组估计对同一个数列项同时成立，门槛必须且只能取N=max{N1,N2}，任何更大的N都不能使用。'
            cases=[{'id':'duplicate','title':'重复的门槛错误：正文与总结同时修订',
                'source':'[来源 样例.txt｜行1]\n已知当n>N1和n>N2时分别有两组估计。要同时使用，只需n大于两者；可取任意N≥max{N1,N2}。这里N1、N2、N、n均为正整数。',
                'requirements':'只解释怎样让两组估计同时成立。保留取最大值的理由、具体例子和最后总结，不出题。',
                'draft':'# 两组估计的统一门槛\n\n要让两组估计对同一个n成立，需要n同时大于N1与N2。\n\n## 选择门槛\n\n'+repeated+
                    '\n\n例如N1=5、N2=8时，n>8即可同时满足。若取N=10，那么n>10当然也同时大于5和8。\n\n## 系统性总结\n\n'+repeated,
                'checks':['相同错误段落出现两次，不能只改一处却隐藏整项疑点','任意N≥max都可用，最大值只是方便选择','保留N1=5、N2=8与N=10的正确例子','无额外模型轮数']}]
        (out/'inputs.json').write_text(j({'cases':cases,'model':'deepseek-flash','effort':'high',
            'review_mode':'fast','tools':False,'history':False,'production_data_modified':False}),encoding='utf-8')
    cases=json.loads((out/'inputs.json').read_text(encoding='utf-8'))['cases'];results=[];cls=traced_class()
    async def sample(case):
        base=cls('deepseek-flash',effort='high');records=[];started=time.perf_counter()
        class Probe:
            async def complete(self,system,user,**kwargs):
                entry={'system':system,'user':user,'json_mode':bool(kwargs.get('json_mode'))}
                records.append(entry);answer=''
                async with asyncio.timeout(300):
                    async for kind,value in base.agent_stream([{'role':'system','content':system},{'role':'user','content':user}],json_mode=entry['json_mode']):
                        if kind=='final':answer=value
                entry['response']=answer
                return answer
        row={'case':case['id'],'phase':phase,'draft_sha256':hashlib.sha256(case['draft'].encode()).hexdigest()}
        try:
            text,reports=await review_explanation(Probe(),case['source'],case['draft'],mode='fast',
                requirements=case['requirements'],summary_level=3,learning_mode='deep',explanation_style='balanced')
            target=out/(case['id']+'-'+phase+'-final.md');target.write_text(text,encoding='utf-8')
            word=out/(case['id']+'-'+phase+'.docx');export_docx(text,case['title'],word)
            row.update(status='completed',answer_file=target.name,docx_file=word.name,characters=len(text),reports=reports,
                answer_sha256=hashlib.sha256(text.encode()).hexdigest())
        except Exception as exc:row.update(status='failed',error_type=type(exc).__name__)
        finally:await base.close()
        row.update(seconds=time.perf_counter()-started,model_requests=len(base.traces),http_attempts=[t.public() for t in base.traces])
        (out/(case['id']+'-'+phase+'-records.json')).write_text(j(records),encoding='utf-8')
        results.append(row);(out/(phase+'-results.json')).write_text(j(results),encoding='utf-8')
        print(json.dumps({k:row[k] for k in ('case','phase','status','seconds','model_requests')}),flush=True)
    await asyncio.gather(*(sample(c) for c in cases))


if __name__=='__main__':asyncio.run(main(sys.argv[1],sys.argv[2],len(sys.argv)>3 and sys.argv[3]=='duplicate'))
