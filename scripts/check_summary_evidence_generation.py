"""Controlled two-chapter job: keep body conditions in the one summary call."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import zipfile
from xml.etree import ElementTree

ROOT=Path(__file__).resolve().parents[1]


async def main(name):
    out=ROOT/'build'/name
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data');os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai,server
    from studyforge.db import create_project,create_job,execute,j,many,now,one,uid,unj
    ai.save_settings({'background_learning_enabled':False,'agent_tools_enabled':False})
    project=create_project('正文条件进入全文总结');sid=uid();path=out/'迭代原资料.txt'
    condition='仅当0<q<2时，迭代才能保证任意初值收敛到0。q=0保持初值，q=2通常交替。'
    path.write_text(condition+'\n'+'原文细节。'*14000,encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (sid,project['id'],path.name,'.txt',str(path),j([{'locator':'预览','text':'STALE_PREVIEW'}]),'ready',now()))
    calls=[];drafts=[];summary_user=[]
    class Client:
        model='controlled-summary';effort='high'
        def fork(self):return Client()
        async def close(self):pass
        async def complete(self,system,user,**kwargs):
            assert 'STALE_PREVIEW' not in user
            calls.append({'system':system,'user':user,'json_mode':bool(kwargs.get('json_mode'))})
            if kwargs.get('json_mode'):return j({'passed':True,'issues':[]})
            if '只补写整篇文章的系统性总结' in system:
                summary_user.append(user);assert condition in user and '【辅助：' in user and len(user)<=48000
                return '## 系统性总结\n本样例强调参数条件：只有0<q<2才保证任意初值趋于0，不能删去参数范围。'
            drafts.append(True)
            return '# 分部讲解\n\n'+('讲解展开。'*3500)+'\n\n## 适用条件\n\n'+condition+'\n\n'+('更多说明。'*3500)+'\n\n## 系统性总结\n迭代用于理解稳定性。'
    server.client_for=lambda *a,**k:Client()
    value=server.GenerateIn(project_id=project['id'],source_ids=[sid],provider='deepseek',model='controlled-summary',
        generation_quality='custom',review_mode='fast',format='docx',exercises=False,parallel=False)
    job=create_job(project['id'],'generate',value.model_dump());start=time.perf_counter()
    await server._generate_job(job,value)
    saved=one('SELECT status,error FROM jobs WHERE id=?',(job,));assert saved['status']=='completed',saved
    assert len(drafts)==2 and len(calls)==5 and len(summary_user)==1
    rows=many('SELECT * FROM artifacts WHERE project_id=?',(project['id'],));assert len(rows)==1
    artifact=rows[0];metadata=unj(artifact['metadata_json'],{});info=metadata['lesson_quality']['summary_body_evidence']
    assert info['included']>=1 and info['fragments'] and info['meaning']=='exact_ai_body_excerpts_not_fact_verification'
    assert not many('SELECT * FROM exercise_sets') and not many('SELECT * FROM mastery')
    with zipfile.ZipFile(artifact['path']) as z:visible=''.join(ElementTree.fromstring(z.read('word/document.xml')).itertext())
    assert condition in visible and '不能删去参数范围' in visible and '【辅助：' not in visible and 'body_evidence' not in visible
    target=out/'长讲解总结条件流程样例.docx';target.write_bytes(Path(artifact['path']).read_bytes())
    result={'passed':True,'controlled_requests':len(calls),'external_model_requests':0,'chapter_writes':len(drafts),
        'fast_reviews':2,'summary_requests':1,'summary_input_characters':len(summary_user[0]),'body_evidence':info,
        'docx_file':target.name,'docx_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'source_reading':metadata['source_reading'],'seconds':time.perf_counter()-start}
    (out/'results.json').write_text(j(result),encoding='utf-8');print(j(result),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
