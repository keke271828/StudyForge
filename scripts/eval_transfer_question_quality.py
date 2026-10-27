"""One real model exercise trial on synthetic sources; never a learner database.

Only final responses are retained. A successful audit is not semantic proof;
inspect every question, worked solution, and claimed change independently.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time


async def run(folder):
    root=Path(__file__).resolve().parents[1];out=root/'build'/folder;out.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'isolated-data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai,exercises,learning_goals as goals
    from studyforge.db import create_project,execute,j,now,uid,unj,one
    from studyforge.exporters import export_document
    ai.save_settings({'agent_network_enabled':False,'agent_tools_enabled':False,'background_learning_enabled':False})
    source=('实数数列收敛到a的定义：对于任意ε>0，存在正整数N，使所有n>N满足|x_n-a|<ε。'
        'ε先给定，N可以依赖ε，不依赖后面所选的n。收敛数列的极限唯一。'
        '假设同时收敛到a和b且a<b，取ε=(b-a)/2>0。由定义分别得到N1、N2；'
        '当n>max(N1,N2)，同时有x_n<(a+b)/2与x_n>(a+b)/2，矛盾。'
        '开邻域不包含共同中点；也可以选ε=(b-a)/3等更小半径。'
        '有限个初始项不影响收敛定义；不声称每一项都落在指定邻域。')
    original=out/'极限唯一性_合成原材料.txt';original.write_text(source,encoding='utf-8')
    project=create_project('新情境检查真实模型抽样');sid=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (sid,project['id'],original.name,'.txt',str(original),'ready',now()))
    goal=goals.save(project['id'],{'name':'数列极限唯一性','domain':'数学','intent':'deep','source_ids':[sid],
        'criterion':'解释量词、选择邻域和统一门槛的理由，并核对变化后的条件与陈述。'})
    baseline=uid();old=[{'index':0,'question':'用自己的话解释数列收敛的定义，说明N可依赖哪些量。','topic':goal['name']},
        {'index':1,'question':'两个极限a<b时为什么可选半距离作为ε，并取两个门槛的最大值？','topic':goal['name']},
        {'index':2,'question':'两个开邻域要怎样选择半径才能不相交？说明半距离及更小半径的区别。','topic':goal['name']}]
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(baseline,project['id'],j([sid]),'合成参考检查',j(old),
        j([{'index':i,'solution':'合成基准的私有答案，未传入本次模型。','rubric':'基准评分'} for i in range(3)]),2,'passed',now()))
    goals.register_check(baseline,project['id'],goals.check_spec(goals.get(goal['id'],project['id'])))
    execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',(uid(),baseline,j(['合成基准已完整作答。']*3),
        j({'scores':[85]*3,'grading_verification_required':False,'practice_context':{'used_notes':False}}),85,'{}',now()))
    spec=goals.check_spec(goals.get(goal['id'],project['id']),'new_context')
    calls=[];client=ai.DeepSeekClient('deepseek-flash',effort='high')
    class Recorded:
        async def complete(self,system,user,**kwargs):
            start=time.perf_counter()
            try:
                raw=await client.complete(system,user,**kwargs)
                calls.append({'system':system,'user':user,'final_response':raw,'seconds':round(time.perf_counter()-start,2)})
                return raw
            finally:(out/'model-calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
    started=time.perf_counter();report={'model':'deepseek-flash','effort':'high','synthetic_baseline':True,
        'scope':'One source-grounded exercise trial, no actual learner marks and no semantic certification'}
    try:
        ident,reviews=await asyncio.wait_for(exercises.generate_set(Recorded(),project['id'],[sid],
            '[来源 合成原材料｜第1段]\n'+source,'新情境理解检查',2,check_spec=spec),600)
        goals.register_check(ident,project['id'],spec)
        row=one('SELECT * FROM exercise_sets WHERE id=?',(ident,))
        public=exercises.public_set(ident)
        private=unj(row['solutions_json'],[])
        (out/'student.json').write_text(j(public),encoding='utf-8')
        (out/'private-solutions-and-audit.json').write_text(j({'solutions':private,'reviews':reviews}),encoding='utf-8')
        path=export_document(exercises.student_document(ident),'docx','新情境理解检查_实际模型抽样','新情境理解检查_实际模型抽样.docx')
        (out/'reference.json').write_text(j(spec),encoding='utf-8')
        report.update(status='completed',model_calls=len(calls),questions=len(public['questions']),word_file=str(path),
                      private_fields_hidden=all(secret not in j(public) for item in private for key in ('solution','context_change') if (secret:=item.get(key))))
    except Exception as exc:report.update(status='failed',model_calls=len(calls),error=str(exc) or type(exc).__name__)
    finally:
        await client.close();report['seconds']=round(time.perf_counter()-started,2)
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder');args=parser.parse_args();asyncio.run(run(args.folder))
