"""Two bounded real generation trials from synthetic completed followups."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


async def main(name):
    folder=ROOT/'build'/name
    if (folder/'results.json').exists():raise SystemExit('Preserve previous results; use a new folder.')
    folder.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    (folder/'runtime-manifest.json').write_text(json.dumps({
        'source_hashes':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in (
            'studyforge/lesson_checks.py','studyforge/exercises.py','studyforge/server.py','studyforge/review.py')},
        'isolated_data':True,'synthetic_teaching_records':True,'network_tools':False,
        'whole_task_attempts':1,'per_case_timeout_seconds':420},ensure_ascii=False,indent=2),encoding='utf-8')
    from studyforge import ai,server,lesson_checks
    from studyforge.db import one,unj
    from studyforge.library_semantic import set_enabled
    from scripts.lesson_check_fixture import seed
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':False,'agent_network_enabled':False,
        'background_learning_enabled':False,'model_concurrency':2})
    set_enabled(False)
    native=server.client_for;records=[];results=[]
    class Recorded:
        def __init__(self,client):self.client=client
        def __getattr__(self,key):return getattr(self.client,key)
        async def complete(self,system,user,**kw):
            row={'system':system,'user':user,'json_mode':kw.get('json_mode',False)};records.append(row);start=time.perf_counter()
            try:
                result=await self.client.complete(system,user,**kw);row['final_response']=result;return result
            finally:
                row['seconds']=round(time.perf_counter()-start,2)
                (folder/'private-final-model-records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'component_call':len(records),'seconds':row['seconds'],'completed':'final_response' in row}),flush=True)
    server.client_for=lambda *a,**kw:Recorded(native(*a,**kw))
    server.start_job=lambda ident,operation:operation.close()  # Run one attempt directly, without whole-task automatic retries.
    for key in ('math','causal'):
        case=seed(folder/key,key);spec=lesson_checks.build(case['questionnaire_id'],case['project_id'],case['conversation_id'])
        (folder/(key+'-context.json')).write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
        start=time.perf_counter();before=len(records)
        result={'case':key,'model':'deepseek-flash','effort':'high','synthetic_teaching_records':True,'tools':False}
        try:
            job=await server.check_lesson_followup(case['questionnaire_id'],server.LessonCheckIn(project_id=case['project_id'],conversation_id=case['conversation_id']))
            saved=one('SELECT payload_json FROM jobs WHERE id=?',(job['job_id'],));value=server.GenerateIn(**unj(saved['payload_json']))
            await asyncio.wait_for(server._generate_job(job['job_id'],value),420)
            state=one('SELECT status,error FROM jobs WHERE id=?',(job['job_id'],));result.update(job_id=job['job_id'],**state)
            link=lesson_checks.latest(case['questionnaire_id'])
            if state['status']=='completed':
                from studyforge.exercises import public_set,student_document
                student=public_set(link['exercise_set_id'],reveal=True)
                assert len(student['questions'])==1 and 'solutions' not in student
                text=student_document(link['exercise_set_id']);file=key+'-student.md';(folder/file).write_text(text,encoding='utf-8',newline='')
                (folder/(key+'-student.json')).write_text(json.dumps(student,ensure_ascii=False,indent=2),encoding='utf-8')
                private=one('SELECT solutions_json FROM exercise_sets WHERE id=?',(link['exercise_set_id'],))
                (folder/(key+'-private-quality-review.json')).write_text(private['solutions_json'],encoding='utf-8')
                artifact=one("SELECT path FROM artifacts WHERE json_extract(metadata_json,'$.generation_job_id')=? AND kind='exercise'",(job['job_id'],))
                target=folder/(case['title']+'_补讲理解检查_无答案.docx');shutil.copyfile(artifact['path'],target)
                result.update(student_file=file,student_sha256=hashlib.sha256(text.encode()).hexdigest(),word_file=str(target),exercise_set_id=link['exercise_set_id'])
        except Exception as exc:result.update(status='failed',error=type(exc).__name__+': '+str(exc))
        result.update(component_calls=len(records)-before,seconds=round(time.perf_counter()-start,2))
        results.append(result);(folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=True),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
