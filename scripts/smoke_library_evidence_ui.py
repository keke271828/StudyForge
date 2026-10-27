"""Real document pipeline, Electron/paired TLS UI; isolated DB and mocked AI."""
import asyncio
import json
from pathlib import Path

from scripts import smoke_library_ui as fixture
from studyforge import library,library_annotations
from studyforge.db import create_job,execute,j,many,now,one,uid,unj

fixture.enable_semantic(False)
n=library.update_node(fixture.nodes[1]['id'],{'start_page':1,'end_page':2,'end_y':.5,'confirmed':True})
warnings=[f'原页公式 {i+1}：保留非零条件，扫描字符仍需核对。' for i in range(12)]


def reading(model,marker,stamp):
    ident=uid()
    signature=library.reading_signature(fixture.b,n,'deepseek',model,'high',vision_model='saved-scan-reader')
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at,vision_model) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(ident,n['id'],signature,'deepseek',model,'high','completed',marker+'_NOTE',j(warnings),now(),stamp,'saved-scan-reader'))
    for number in range(1,3):
        page=library.extract_page(fixture.b,n,number,ocr=False)
        execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',
            (ident,number,page['locator'],marker+'\n'+page['original_text'],'图像核对：非零除数条件。',page['image_path'],page['image_sha256']))
    return ident


old=reading('saved-reading-model','ORIGINAL_VERSION',now())
library_annotations.save(n['id'],old,True,'请核对非零除数条件；<img src=x onerror="window.evidenceInjected=true"> 仅为用户文字。',0)
library.set_preferences(fixture.c['id'],fixture.p['id'],'manual',[{'node_id':n['id'],'purpose':'primary'}])
snapshot=library.reference_snapshot(fixture.c['id'],fixture.p['id'],'封闭性')
context=library.reference_content(snapshot,'封闭性')['text']
new=reading('later-reading-model','NEWER_VERSION','2099-01-01T00:00:00+00:00')
fixture.case.update(old_reading_id=old,new_reading_id=new)


async def main():
    value=fixture.server.GenerateIn(project_id=fixture.p['id'],conversation_id=fixture.c['id'],source_ids=[],
        provider='deepseek',model='fixture-writer',reasoning_effort='none',review_mode='express',
        format='docx',library_snapshot=snapshot,library_context=context)
    job=create_job(fixture.p['id'],'generate',value.model_dump())
    await fixture.server._generate_job(job,value)
    row=one('SELECT * FROM jobs WHERE id=?',(job,))
    if row['status']!='completed':raise RuntimeError(row['error'])
    artifact=many("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(fixture.p['id'],))[0]
    metadata=unj(artifact['metadata_json'])
    assert metadata['source_reading'][0]['library_reading']['id']==old
    assert library.ready_reading(n,metadata_only=True)['id']==new
    legacy=json.loads(j(metadata));legacy.pop('generation_job_id',None)
    for source in legacy['source_reading']:
        source.pop('library_reading',None);source.pop('scope',None)
    legacy_artifact=fixture.server.add_artifact(fixture.p['id'],[],'explanation','docx','旧版本记录验收',Path(artifact['path']),legacy)
    fixture.case.update(artifact_id=artifact['id'],legacy_artifact_id=legacy_artifact['id'],model_requests=len(fixture.calls))
    await fixture.main()


if __name__=='__main__':asyncio.run(main())
