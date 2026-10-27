"""Same submitted work: full re-diagnosis versus per-question continuation."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def scenario(homework,j):
    questions=[
        {'index':0,'topic':'一元一次方程','question':'解方程2x+3=7，并写出等价变形步骤。'},
        {'index':1,'topic':'整数加法','question':'计算2+3，写出核对步骤。'},
        {'index':2,'topic':'高斯定律','question':'闭合面内净电荷为零，能否推出电场处处为零？解释理由。'}]
    worksheet={'id':'synthetic-set','title':'分题补讲对照','difficulty':2,'questions_json':j(questions),
        'solutions_json':j([
            {'index':0,'solution':'两边减3得2x=4，再同时除以2得x=2。代回2×2+3=7。','rubric':'等式两边施加同样的合法操作，结果代回。'},
            {'index':1,'solution':'2+3=5；可用5-3=2核对。','rubric':'加法与逆运算正确。'},
            {'index':2,'solution':'不能。均匀场穿过立方体，顶底通量相消、侧面为零，净通量零但电场不为零。','rubric':'区分整体有向积分与逐点场值。'}])}
    options={'provider':'deepseek','model':'deepseek-flash','reasoning_effort':'high','coding':False,
        'teaching':{'learning_mode':'deep','explanation_style':'balanced','output_language':'zh'},
        'profile':{'items':[{'topic':'高斯定律','summary':'曾询问通量概念的含义；历史自报，不能直接推断当前能力。'}]}}
    row={'id':'synthetic-attempt','exercise_set_id':worksheet['id'],'project_id':'isolated-project','conversation_id':'isolated-chat',
        'source_version':homework.version(worksheet),'answers_json':j(['4','2+3=4','净通量是零，所以面内每处电场都是零。']),
        'analysis_json':'{}','options_json':j(options)}
    grade={'scores':[30,70,40],'score':46.7,'feedback':['只写结果且不正确，尚缺推理步骤。','加法计算错误。','误将净通量零当作处处场零。']}
    prior=[{'index':1,'kinds':['implementation'],'text':'我把加3算成了加2。'},
           {'index':2,'kinds':['terminology'],'text':'我把穿过整个面的通量和一个点的电场当成同一个量。'}]
    current=sorted(prior+[{'index':0,'kinds':['implementation'],'text':'我做了7减3得4，忘记还要除以2。'}],key=lambda item:item['index'])
    return row,worksheet,grade,prior,current


async def main():
    if '--live' not in sys.argv:raise SystemExit('Pass --live for the configured provider.')
    out=ROOT/'build'/sys.argv[1]
    if out.exists():raise SystemExit('Use a fresh output folder.')
    out.mkdir(parents=True);os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    from studyforge import ai,homework
    from studyforge.db import j
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False,'model_concurrency':2})
    row,worksheet,grade,prior,current=scenario(homework,j)
    saved={'row':row,'worksheet':worksheet,'grade':grade,'prior_causes':prior,'current_causes':current}
    (out/'scenario.json').write_text(j(saved),encoding='utf-8')
    ns={'__name__':'studyforge.old_homework','__package__':'studyforge'}
    path=ROOT/'build/homework-analysis-reuse-20261022/baseline-homework.py'
    exec(compile(path.read_text(encoding='utf-8'),str(path),'exec'),ns)
    results=[]
    async def sample(arm,operation):
        started=time.perf_counter();record={'arm':arm,'model':'deepseek-flash','effort':'high','calls':[]}
        class Client(ai.DeepSeekClient):
            async def _post(self,body,timeout=240,retry=True):
                if len(record['calls'])>=2:raise RuntimeError('Bounded probe: no more than one format repair.')
                public=copy.deepcopy(body)
                for message in public['messages']:message.pop('reasoning_content',None)
                file=arm+'-request-'+str(len(record['calls'])+1)+'.json';(out/file).write_text(j(public),encoding='utf-8')
                call={'file':file,'sha256':hashlib.sha256(j(public).encode()).hexdigest()};record['calls'].append(call)
                packet=await super()._post(body,timeout,retry=False)
                if packet.get('usage'):call['usage']=packet['usage']
                raw=packet.get('choices',[{}])[0].get('message',{}).get('content','')
                raw_file=arm+'-raw-'+str(len(record['calls']))+'.json';(out/raw_file).write_text(raw,encoding='utf-8');call['raw_file']=raw_file
                return packet
        client=Client('deepseek-flash',effort='high');value=None
        try:
            async with asyncio.timeout(360):value=await operation(client)
            file=arm+'-analysis.json';(out/file).write_text(j(value),encoding='utf-8')
            record.update(status='completed',analysis_file=file,items=len(value['items']),reuse=value.get('analysis_reuse'))
        except Exception as exc:record.update(status='failed',error=type(exc).__name__+': '+str(exc))
        finally:
            await client.close();record['seconds']=round(time.perf_counter()-started,3);results.append(record)
            (out/'report.json').write_text(j(results),encoding='utf-8')
            print(j({k:v for k,v in record.items() if k not in ('calls','reuse')}),flush=True)
        return value
    initial=await sample('initial',lambda client:homework.analyze(client,row,worksheet,grade,prior))
    if not initial:raise SystemExit('Initial analysis failed; preserve outputs without paired success claims.')
    row['analysis_json']=j(initial)
    await asyncio.gather(
        sample('baseline',lambda client:ns['analyze'](client,copy.deepcopy(row),worksheet,grade,current)),
        sample('fixed',lambda client:homework.analyze(client,copy.deepcopy(row),worksheet,grade,current)))
    expected=[item for item in initial['items'] if item['index'] in (1,2)]
    fixed=out/'fixed-analysis.json'
    if fixed.exists():
        actual=json.loads(fixed.read_text(encoding='utf-8'))
        assert [item for item in actual['items'] if item['index'] in (1,2)]==expected
        assert actual['analysis_reuse']['reused_indices']==[1,2]


if __name__=='__main__':asyncio.run(main())
