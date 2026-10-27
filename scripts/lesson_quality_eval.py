"""Small, source-bound lesson samples; offline by default, human quality review required."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path


CASES = {
    'philosophy': {'title':'实然与应然', 'source':'材料区分描述性判断与规范性判断。描述某行为普遍存在，不足以推出该行为应当被接受；还需明确评价原则。材料未说明这一辨析的首创者。',
                  'review':['解释实然与应然的区别','指出论证缺少的规范前提','不把观点或未知历史归属说成已证事实']},
    'social': {'title':'相关与共同原因', 'source':'观察中变量X与Y相关，但Z可能同时影响X与Y。相关关系本身不能证明X导致Y；还须说明识别假设与证据。这个材料没有给出可识别因果效应的数据。',
               'review':['解释共同原因为何造成困难','区分相关描述与因果主张','不捏造实验、数据或已识别的效应']},
    'math': {'title':'平方构造与不等式', 'source':'令a、b为实数。因为(a-b)^2>=0，展开为a^2-2ab+b^2>=0，故a^2+b^2>=2ab。平方的展开恰有要控制的交叉项；这解释一种可行构造，不证明构造唯一。',
             'review':['说明为何选平方构造','逐步说明非负、展开和移项','保留实数条件，不声称方法唯一']},
    'physics': {'title':'恒质量一维模型', 'source':'本材料只讨论质量m恒定的一维模型，速度v(t)可微，合力F=m dv/dt。加速度为速度随时间的变化率。F的单位为kg·m/s^2；材料没有讨论变质量系统。',
                'review':['解释变化率与方法动机','核对符号和单位','保留恒质量与一维条件，不越界推广']},
    'chemistry': {'title':'给定反应速率模型', 'source':'材料假定反应A+B→C采用模型v=k[A][B]，浓度单位为mol/L，速率单位为mol/(L·s)，因此k的单位为L/(mol·s)。这是给定模型；不能推出所有反应都遵循此速率式。',
                  'review':['解释模型中各量与假设','核对速率常数单位','不把反应方程式直接当作普遍速率规律']},
    'biology': {'title':'反馈结构与稳定性', 'source':'给定一个调节机制：输出偏高时抑制其产生，偏低时促进其产生。这个方向关系称为负反馈，但它本身不保证整个系统稳定；还需考察时延、响应强度等条件。材料未指定具体生物系统。',
                'review':['解释调节方向与反馈结构','区分负反馈和稳定性','不捏造具体生物机制，不强行作物理类比']},
}


async def evaluate(output, case_names, *, live=False, provider=None, model=None, repeat=False):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    old_data = os.environ.get('STUDYFORGE_DATA_DIR')
    os.environ['STUDYFORGE_DATA_DIR'] = str(output/'data')
    from studyforge import ai, server
    from studyforge.db import create_project, create_job, execute, j, now, one, uid, unj, many
    old_factory = server.client_for
    calls=[]
    cfg={'chat_provider':provider or 'deepseek','agent_tools_enabled':False,'agent_web_enabled':False,'background_learning_enabled':False}
    ai.save_settings(cfg)
    class Offline:
        model='offline-fixture'
        async def complete(self, system, user, **kwargs):
            calls.append('simulated')
            source=active['source']
            return f"# {active['title']}（离线流程样例，未调用模型）\n\n> {source} [{active['filename']}｜{active['locator']}]\n\n这是原文复现，用于检查格式与来源协议，不是实际AI讲解。\n\n## 系统性总结\n只能确认流程输出，讲解质量留待实际模型与人工验收。"
    active={}
    try:
        if not live: server.client_for=lambda *args,**kwargs:Offline()
        rows=[]
        for name in case_names:
            case=CASES[name];project=create_project('讲解验收 · '+case['title']);source=uid()
            path=output/(case['title']+'.txt');path.write_text(case['source'],encoding='utf-8')
            execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (source,project['id'],path.name,'.txt',str(path),j([{'locator':'预览','text':'这不是生成依据'}]),'ready',now()))
            from studyforge.parsers import parse_file
            active.update(case,filename=path.name,locator=parse_file(path)[0]['locator'])
            for attempt in range(2 if repeat else 1):
                value=server.GenerateIn(project_id=project['id'],source_ids=[source],provider=provider or 'deepseek',
                                        model=model if live else 'offline-fixture',review_mode='express',summary_level=3,
                                        instructions='只使用给定原文；解释概念、方法理由和条件。未知人物归属注明无法确认。不出题。')
                job=create_job(project['id'],'generate',value.model_dump());start=time.perf_counter()
                await server._generate_job(job,value)
                result=one('SELECT * FROM jobs WHERE id=?',(job,))
                artifact=next((row for row in many('SELECT * FROM artifacts WHERE project_id=?',(project['id'],))
                               if unj(row['metadata_json'],{}).get('generation_job_id')==job),None)
                meta=unj(artifact['metadata_json'],{}) if artifact else {}
                rows.append({'case':name,'title':case['title'],'attempt':attempt+1,'status':result['status'],
                             'error':result['error'],'elapsed_seconds':round(time.perf_counter()-start,3),
                             'document':artifact['path'] if artifact else None,'source_reading':meta.get('source_reading'),
                             'checks':meta.get('lesson_quality'),'human_review_required':case['review'],
                             'human_review':{'coverage':None,'method_motivation':None,'conditions_and_errors':None,
                                             'appropriate_transfer':None,'readability':None}})
        report={'simulated':not live,'provider':provider if live else 'offline','model':model if live else 'offline-fixture',
                'source_only':True,'exercises':False,'passed_semantic_review':None,'cases':rows,
                'note':'离线样例仅验流程；来源匹配不是事实、覆盖、动机解释或学习效果的正确性证明。实际模型输出必须人工填写验收项。'}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    finally:
        server.client_for=old_factory
        if old_data is None:os.environ.pop('STUDYFORGE_DATA_DIR',None)
        else:os.environ['STUDYFORGE_DATA_DIR']=old_data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',action='append',choices=CASES,help='Repeat to select cases; default all six.')
    parser.add_argument('--output',default=str(Path('build')/('lesson-quality-eval-'+uuid.uuid4().hex)))
    parser.add_argument('--live',action='store_true',help='Call an actual model and incur its normal usage; requires provider/model and configured credentials.')
    parser.add_argument('--provider',choices=['codex','deepseek']);parser.add_argument('--model')
    parser.add_argument('--repeat',action='store_true',help='Generate a second version to compare parse reuse; doubles live generation usage.')
    args=parser.parse_args()
    if args.live and (not args.provider or not args.model):parser.error('--live requires --provider and --model')
    if args.live and args.provider=='deepseek' and not os.environ.get('DEEPSEEK_API_KEY'):
        parser.error('Isolated live DeepSeek evaluation requires DEEPSEEK_API_KEY in the process environment; no real settings or saved key are copied.')
    result=asyncio.run(evaluate(args.output,args.case or list(CASES),live=args.live,provider=args.provider,model=args.model,repeat=args.repeat))
    print(json.dumps({'report':str(Path(args.output).resolve()/'report.json'),'simulated':result['simulated'],
                      'completed':sum(row['status']=='completed' for row in result['cases']),'total':len(result['cases'])},ensure_ascii=False))


if __name__=='__main__':main()
