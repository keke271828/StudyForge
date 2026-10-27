"""Controlled actual Word job: generated source identity, no implicit parent IO."""
import asyncio
import hashlib
import os
from pathlib import Path
import sys
import time
import zipfile
from unittest.mock import patch
from xml.etree import ElementTree

ROOT=Path(__file__).resolve().parents[1]


async def main(name):
    out=ROOT/'build'/name
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai,server,artifact_sources,materials
    from studyforge.config import artifacts_dir
    from studyforge.db import create_project,create_job,execute,j,many,now,one,uid,unj
    from studyforge.source_origins import RULES
    ai.save_settings({'background_learning_enabled':False,'agent_tools_enabled':False})
    project=create_project('再次引用讲解的资料身份');parent=uid();aid=uid()
    missing=out/'未选择且不存在的教材.txt'
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (parent,project['id'],missing.name,'.txt',str(missing),j([{'locator':'预览','text':'UNSELECTED_PARENT_PREVIEW'}]),'ready',now()))
    path=artifacts_dir()/'旧AI讲解.txt'
    path.write_text('# 极限唯一性\n这份讲解引用未提供的教材，说明两个开邻域不相交的方法。最后一句：正数半径可以选择得更小。',encoding='utf-8')
    execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)',(aid,project['id'],j([parent]),'explanation','txt',str(path),'旧AI讲解','{}',now()))
    artifact_sources.sync_project(project['id'])
    selected=one('SELECT s.* FROM sources s JOIN artifact_sources x ON x.source_id=s.id WHERE x.artifact_id=?',(aid,))
    calls=[];parsed=[];real_parse=materials.parsed_original
    def parse(file,digest):
        assert file==path,'Only the selected artifact may be parsed'
        parsed.append(str(file));return real_parse(file,digest)
    class Client:
        model='controlled-provenance';effort='high'
        def fork(self):return Client()
        async def close(self):pass
        async def complete(self,system,user,**kwargs):
            calls.append({'system':system,'user':user,'json_mode':bool(kwargs.get('json_mode'))})
            assert 'ai_generated_artifact' in user and 'UNSELECTED_PARENT_PREVIEW' not in user
            if kwargs.get('json_mode'):return j({'passed':True,'issues':[]})
            assert RULES in system and '正数半径可以选择得更小' in user
            return ('# 两个邻域为什么能给出矛盾\n\n这份已有讲解讨论极限唯一性，没有在本次重新读取它引用的教材。'
                '这里解释讲解中的构造：选择两个不相交的开邻域，就能排除同一项同时落入两边。'
                '\n\n## 系统性总结\n邻域互不相交产生矛盾；本次依据是所选讲解，不能声称已经核对教材原文。')
    with patch.object(server,'client_for',lambda *a,**k:Client()),patch.object(materials,'parsed_original',parse):
        value=server.GenerateIn(project_id=project['id'],source_ids=[selected['id']],provider='deepseek',model='controlled-provenance',
            generation_quality='custom',review_mode='fast',format='docx',exercises=False)
        job=create_job(project['id'],'generate',value.model_dump());start=time.perf_counter()
        await server._generate_job(job,value)
    saved=one('SELECT status,error FROM jobs WHERE id=?',(job,));assert saved['status']=='completed',saved
    (out/'model-records.json').write_text(j(calls),encoding='utf-8')
    observed={'requests':len(calls),'json_requests':sum(c['json_mode'] for c in calls),'parsed':parsed}
    (out/'observations.json').write_text(j(observed),encoding='utf-8')
    assert len(calls)==2 and sum(c['json_mode'] for c in calls)==1 and parsed and set(parsed)=={str(path)},observed
    rows=many('SELECT * FROM artifacts WHERE project_id=? AND id<>?',(project['id'],aid));assert len(rows)==1
    artifact=rows[0];metadata=unj(artifact['metadata_json'],{});origin=metadata['source_reading'][0]['content_origin']
    assert origin['role']=='ai_generated_artifact' and origin['artifact_id']==aid and unj(artifact['source_ids_json'],[])==[selected['id']]
    assert not many('SELECT * FROM exercise_sets') and not many('SELECT * FROM mastery')
    with zipfile.ZipFile(artifact['path']) as z:visible=''.join(ElementTree.fromstring(z.read('word/document.xml')).itertext())
    assert '不能声称已经核对教材原文' in visible and 'content_origin' not in visible and '所选资料身份JSON' not in visible
    target=out/'引用已有AI讲解的Word流程样例.docx';target.write_bytes(Path(artifact['path']).read_bytes())
    result={'passed':True,'controlled_requests':len(calls),'external_model_requests':0,'fast_reviews':1,'summary_requests':0,
        'only_selected_file_parsed':parsed,'unselected_parent_not_read':True,'parent_file_exists':missing.exists(),
        'source_reading':metadata['source_reading'],'docx_file':target.name,
        'docx_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'seconds':time.perf_counter()-start}
    (out/'results.json').write_text(j(result),encoding='utf-8')
    (out/'model-records.json').write_text(j(calls),encoding='utf-8');print(j(result),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
