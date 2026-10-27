"""Actual export and desktop/paired mobile UI with frozen background receipts."""
import asyncio
import json
from pathlib import Path

from scripts import smoke_library_ui as fixture
from studyforge import library,library_annotations,library_history
from studyforge.db import create_job,execute,j,many,now,one,uid,unj

fixture.enable_semantic(False)
primary=library.update_node(fixture.nodes[1]['id'],{'start_page':1,'end_page':2,'end_y':.5,'confirmed':True})
background=library.update_node(fixture.nodes[2]['id'],{'start_page':2,'end_page':3,'start_y':.2,'end_y':.5,'confirmed':True})
warnings=[f'原页公式 {i+1}：保留非零条件，扫描字符仍需核对。' for i in range(12)]


def reading(node,model,marker,stamp):
    ident=uid();signature=library.reading_signature(fixture.b,node,'deepseek',model,'high',vision_model='saved-scan-reader')
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at,vision_model) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(ident,node['id'],signature,'deepseek',model,'high','completed',marker+'_NOTE '*500,j(warnings),now(),stamp,'saved-scan-reader'))
    for number in range(node['start_page'],node['end_page']+1):
        page=library.extract_page(fixture.b,node,number,ocr=False)
        text=marker+'\n'+page['original_text']
        if node['id']==background['id']:text+='\n'+'Retain the assumptions and distinguish examples. '*250+' nonzero conditions must be checked.'
        execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',
            (ident,number,page['locator'],text,'图像核对：非零除数条件。',page['image_path'],page['image_sha256']))
    return ident


old=reading(primary,'saved-reading-model','ORIGINAL_VERSION',now())
old_background=reading(background,'saved-background-model','BACKGROUND_VERSION',now())
for node,ident in [(primary,old),(background,old_background)]:
    library_annotations.save(node['id'],ident,True,'请核对非零除数条件；<img src=x onerror="window.evidenceInjected=true"> 仅为用户文字。',0)
library.set_preferences(fixture.c['id'],fixture.p['id'],'manual',[{'node_id':primary['id'],'purpose':'primary'},
    {'node_id':background['id'],'purpose':'reference'}])
snapshot=library.reference_snapshot(fixture.c['id'],fixture.p['id'],'nonzero conditions')
result=library.reference_content(snapshot,'nonzero conditions')
receipt=library.reference_receipt(result)
omitted_lookup=library_history.record(fixture.c['id'],fixture.p['id'],'参考预算不足',
    library.reference_content(snapshot,'nonzero conditions',max_chars=100))
lookup=library_history.record(fixture.c['id'],fixture.p['id'],'nonzero conditions',result)
new=reading(primary,'later-reading-model','NEWER_VERSION','2099-01-01T00:00:00+00:00')
new_background=reading(background,'later-background-model','NEWER_BACKGROUND','2099-01-01T00:00:00+00:00')
fixture.case.update(old_reading_id=old,new_reading_id=new,old_background_id=old_background,
    new_background_id=new_background,lookup_id=lookup['id'],reference_node_id=background['id'],
    omitted_lookup_id=omitted_lookup['id'],
    reference_characters=receipt['context_characters'],reference_hash=receipt['context_sha256'])


async def main():
    value=fixture.server.GenerateIn(project_id=fixture.p['id'],conversation_id=fixture.c['id'],source_ids=[],
        provider='deepseek',model='fixture-writer',reasoning_effort='none',review_mode='express',
        format='docx',library_snapshot=snapshot,library_context=result['text'],library_evidence=receipt)
    job=create_job(fixture.p['id'],'generate',value.model_dump())
    await fixture.server._generate_job(job,value)
    row=one('SELECT * FROM jobs WHERE id=?',(job,))
    if row['status']!='completed':raise RuntimeError(row['error'])
    normal=many("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(fixture.p['id'],))[0]
    # Exercise the real multi-part writer and its separate reference budget.
    native=fixture.server.explanation_batches
    fixture.server.explanation_batches=lambda digest:[digest+'\n首部标记',digest+'\n后部标记']
    try:
        job=create_job(fixture.p['id'],'generate',value.model_dump())
        await fixture.server._generate_job(job,value)
        row=one('SELECT * FROM jobs WHERE id=?',(job,))
        if row['status']!='completed':raise RuntimeError(row['error'])
    finally:fixture.server.explanation_batches=native
    artifact=one('SELECT * FROM artifacts WHERE id=?',(unj(row['result_json'])['artifacts'][0]['id'],))
    metadata=unj(artifact['metadata_json'])
    assert metadata['source_reading'][0]['library_reading']['id']==old
    actual=metadata['library_evidence']
    assert actual['context_characters']<=6000 and actual['shared_chapter_count']==2
    fixture.case.update(normal_artifact_id=normal['id'],reference_characters=actual['context_characters'],
        reference_hash=actual['context_sha256'],lookup_hash=receipt['context_sha256'],shared_chapter_count=2)
    legacy=json.loads(j(metadata));legacy.pop('generation_job_id',None);legacy.pop('library_evidence',None)
    for source in legacy['source_reading']:
        source.pop('library_reading',None);source.pop('scope',None)
    legacy_artifact=fixture.server.add_artifact(fixture.p['id'],[],'explanation','docx','旧版本记录验收',Path(artifact['path']),legacy)
    fixture.case.update(artifact_id=artifact['id'],legacy_artifact_id=legacy_artifact['id'],model_requests=len(fixture.calls))
    await fixture.main()


if __name__=='__main__':asyncio.run(main())
