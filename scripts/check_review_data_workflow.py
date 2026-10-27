"""Controlled complete generation, audit/rewrite and actual DOCX, isolated data."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]


async def main(name):
    folder=ROOT/'build'/name
    if folder.exists() and any(folder.iterdir()):raise SystemExit('Use a fresh output folder.')
    folder.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai,conversations,server
    from studyforge.db import create_job,create_project,execute,j,many,now,one,uid,unj
    from studyforge.review_input import MARKER
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False,'model_concurrency':2})
    original='完整资料：只给x∈[0,1]，端点1允许出现；不能推出x<1。FULL_SOURCE_END'
    source_path=folder/'闭区间原资料.txt';source_path.write_text(original,encoding='utf-8')
    note='## 来源定位需核对\n\n- 引用块2：先前未能逐字匹配，需对照原文件。'
    draft='# 闭区间\n\nOLD_DRAFT：x∈[0,1]说明x<1。\n\n'+note+'\n\n## 系统性总结\n\n端点不可取。'
    revised='# 闭区间\n\nx∈[0,1]说明0≤x≤1，端点1允许出现。\n\n## 系统性总结\n\n不能把包含端点的条件加强成严格小于。'
    rows=[]
    for mode,expected in [('balanced',3),('strict',8)]:
        project=create_project('完整流程 · '+mode);chat=conversations.create(project['id'],'deepseek','deepseek-flash');sid=uid()
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (sid,project['id'],source_path.name,'.txt',str(source_path),j([{'locator':'预览','text':'STALE_PREVIEW_NOT_SOURCE'}]),'ready',now()))
        calls=[]
        class Client:
            model='controlled-review-data';effort='high'
            def fork(self):return Client()
            async def close(self):pass
            async def complete(self,system,user,json_mode=False,**kwargs):
                calls.append({'system':system,'user':user,'json_mode':json_mode})
                assert 'FULL_SOURCE_END' in user and 'STALE_PREVIEW_NOT_SOURCE' not in user
                if MARKER not in user:return draft
                data=json.loads(user.split(MARKER,1)[1]);assert original in data['source_text']
                if not json_mode:
                    assert data['review_reports'];return revised
                old='OLD_DRAFT' in data['explanation_text']
                if not old:assert '先前未能逐字匹配' in data['explanation_text']
                return j({'passed':not old,'issues':[{'location':'端点','problem':'闭区间不能推出严格内点'}] if old else []})
        server.client_for=lambda *a,**kw:Client()
        value=server.GenerateIn(project_id=project['id'],conversation_id=chat['id'],source_ids=[sid],provider='deepseek',
            model='deepseek-flash',review_mode=mode,output_format='docx',instructions='只使用这份原文解释闭区间，不出题。')
        job=create_job(project['id'],'generate',value.model_dump());start=time.perf_counter()
        await server._generate_job(job,value)
        saved=one('SELECT status,error,result_json FROM jobs WHERE id=?',(job,));assert saved['status']=='completed',saved
        artifact=next(a for a in many('SELECT * FROM artifacts WHERE project_id=?',(project['id'],)) if a['kind']=='explanation')
        meta=unj(artifact['metadata_json'],{})
        assert any(r.get('input_scope') for r in meta['reviews']) and any(r.get('revision_cautions',{}).get('restored_sections')==1 for r in meta['reviews'])
        assert len(calls)==expected,(mode,len(calls))
        with zipfile.ZipFile(artifact['path']) as archive:xml=archive.read('word/document.xml').decode()
        assert '先前未能逐字匹配' in xml and '不能把包含端点' in xml
        assert 'OLD_DRAFT' not in xml and 'explanation_text' not in xml and 'schema_version' not in xml
        assert many('SELECT * FROM mastery')==[] and many('SELECT * FROM exercise_sets')==[]
        output=folder/(mode+'-完整流程核查样例.docx');output.write_bytes(Path(artifact['path']).read_bytes())
        rows.append({'mode':mode,'passed':True,'controlled_model_requests':len(calls),'external_model_requests':0,
            'seconds':time.perf_counter()-start,'docx_file':output.name,'docx_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'source_reading':meta['source_reading'],'review_reports':meta['reviews']})
        (folder/'results.json').write_text(j(rows),encoding='utf-8')
        print(json.dumps({'mode':mode,'passed':True,'controlled_model_requests':len(calls),'external_model_requests':0}),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
