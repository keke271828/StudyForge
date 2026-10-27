"""Bounded real tutor/document agent tool checks, isolated from learner data."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


async def main(name,boundary=False,polynomial=False):
    out=ROOT/'build'/name
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai
    from studyforge.agent_tools import AgentRuntime
    from studyforge.db import create_project,j,many
    from studyforge.teaching_policy import TEACHER_PERSONA,CHAT_RULES
    from studyforge.teaching_styles import style_policy
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':True,'agent_permission_mode':'read_only',
        'agent_network_enabled':False,'background_learning_enabled':False,'agent_max_tool_calls':4,'model_concurrency':2})
    cls=traced_class();results=[]
    for role in ('tutor','lecture'):
        project=create_project('数学工具真实验收 · '+role)
        runtime=AgentRuntime(project['id'],provider='deepseek',model='deepseek-flash',effort='high',publishing=False)
        native=cls('deepseek-flash',effort='high',agent_runtime=runtime)
        original=native.stream_packets
        async def bounded(body):
            if len(native.traces)>=3:raise RuntimeError('Bounded tool probe model-request limit')
            async for packet in original(body):yield packet
        native.stream_packets=bounded
        question=('有人说“两个非零向量的点积为正，就代表同向”，对吗？请用数学核验工具检查a=(1,0)、b=(1,1)，'
            '再用一次批量算术核验0.1+0.2和1/3+1/6。解释这组例子能说明什么、不能说明什么。不出题，约500字。')
        if boundary:question=('请用数学核验工具分别检查(1,0)与(2,0)、(1,0)与(-2,0)、(0,0)与(1,1)的点积和方向。'
            '“正点积一定是锐角、负点积一定是钝角、零向量与任何向量垂直”这三句话严谨吗？'
            '只补讲这些边界，说明数例与一般依据的区别，不出题，约500字。')
        if polynomial:
            question=(
                '我把柯西配方整理为A*(A*t**2+2*B*t+C)-(A*t+B)**2=A*C+B**2，想用它证明B**2<=A*C。'
                '请用本机数学核验工具检查这条多项式恒等式，再讲清错误在哪、应怎样改，'
                'A>0时怎样从平方和非负接回目标，以及A=0怎么办。不布置习题，避免只靠几个数值例子证明恒等。'
                if role=='tutor' else
                '我写能量E=m*v**2/2+k*x**2/2，所以对x的偏导是2*k*x，对v的偏导是m*v。'
                'E不显含t，就能说总时间导数为0吧？请用本机多项式核验工具检查两项偏导，'
                '把m,k视为常数、x,v视为独立形式变量；然后另用链式法则与给定运动方程解释总时间导数。'
                '若结论在本模型里成立但我的理由不成立，要分别说清。最后总结，不出题。')
        start=time.perf_counter();row={'role':role,'question':question,'model':'deepseek-flash','effort':'high'}
        try:
            async with asyncio.timeout(240):
                if role=='lecture':answer=await ai.generate_explanation(native,
                    (r'一维给定模型m x″=−kx，其中m,k为正常数，v=x′。能量表达式E=mv²/2+kx²/2，x,v沿时间变化。'
                     if polynomial else '本资料讨论非零实向量。点积为各对应分量乘积的和，同向要求一个向量是另一个的正倍数。'),
                    3,[],style='balanced',requirements=question)
                else:answer=await native.complete(TEACHER_PERSONA+CHAT_RULES+style_policy('balanced'),question)
            (out/(role+'-final.md')).write_text(answer,encoding='utf-8');row.update(status='completed',answer_file=role+'-final.md')
        except BaseException as exc:row.update(status='failed',error_type=type(exc).__name__)
        finally:await native.close()
        events=many('SELECT tool,status,result_json FROM agent_tool_events WHERE project_id=?',(project['id'],))
        # The next HTTP request includes provider-private reasoning. Retain only
        # public text/tool calls and results, never reasoning_content or headers.
        public=[]
        for body in native.request_bodies:
            messages=[{k:v for k,v in m.items() if k!='reasoning_content'} for m in body['messages']]
            public.append({'model':body['model'],'messages':messages})
        (out/(role+'-public-wire.json')).write_text(j(public),encoding='utf-8')
        row.update(seconds=time.perf_counter()-start,model_requests=len(native.traces),http_attempts=[t.public() for t in native.traces],tool_events=events)
        results.append(row);(out/'results.json').write_text(j(results),encoding='utf-8')
        print(json.dumps({'role':role,'status':row['status'],'seconds':round(row['seconds'],2),'model_requests':row['model_requests'],
            'tools':[e['tool'] for e in events]},ensure_ascii=True),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1],boundary='--boundary' in sys.argv[2:],polynomial='--polynomial' in sys.argv[2:]))
