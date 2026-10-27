"""Native read/generate -> desktop + paired HTTPS phone, isolated mocked AI."""
import asyncio
import copy
from pathlib import Path

from scripts import smoke_library_ui as fixture
from studyforge import server
from studyforge.db import create_job,execute,j,many,now,one,uid,unj

fixture.enable_semantic(False)


async def main():
    ids=[]
    for label in ('甲','乙'):
        path=fixture.case_path.parent/(label+'原资料.txt')
        path.write_text('数域对四则运算封闭，除法要求除数非零。资料'+label+'。',encoding='utf-8')
        ident=uid();ids.append(ident)
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
                (ident,fixture.p['id'],path.name,'.txt',str(path),'ready',now()))
    value=server.ReadIn(project_id=fixture.p['id'],source_ids=ids,provider='deepseek',model='fixture-writer',generation_quality='custom')
    job=create_job(fixture.p['id'],'read',value.model_dump())
    await server._read_job(job,value)
    saved=one('SELECT * FROM jobs WHERE id=?',(job,));assert saved['status']=='completed',saved['error']
    rid=unj(saved['result_json'])['reading_id']
    notes=unj(one('SELECT notes_json FROM reading_sessions WHERE id=?',(rid,))['notes_json'])
    cases=[]
    for kind in ('matched','legacy','unmatched'):
        stored=copy.deepcopy(notes)
        if kind=='legacy':
            for row in stored:row.pop('input_scope',None)
        execute('UPDATE reading_sessions SET notes_json=? WHERE id=?',(j(stored),rid))
        value=server.GenerateIn(project_id=fixture.p['id'],conversation_id=fixture.c['id'],
            source_ids=ids[::-1] if kind=='unmatched' else ids,reading_id=rid,provider='deepseek',model='fixture-writer',
            generation_quality='custom',review_mode='express',format='docx',exercises=False)
        job=create_job(fixture.p['id'],'generate',value.model_dump())
        await server._generate_job(job,value)
        saved=one('SELECT * FROM jobs WHERE id=?',(job,));assert saved['status']=='completed',saved['error']
        artifact=next(row for row in many('SELECT * FROM artifacts WHERE project_id=?',(fixture.p['id'],))
                      if unj(row['metadata_json'],{}).get('generation_job_id')==job)
        meta=unj(artifact['metadata_json']);receipt=meta['lesson_quality']['reading_note_inputs'][0]
        expected={'matched':'exact_original_input','legacy':'legacy_unassigned','unmatched':'no_matching_original_input'}[kind]
        assert receipt['reason']==expected
        cases.append({'kind':kind,'artifact_id':artifact['id'],'receipt':receipt,'metadata':meta})
    fixture.case.update(reading_note_cases=cases,model_requests=len(fixture.calls))
    assert len(fixture.calls)==4
    (fixture.case_path.parent/'native-results.json').write_text(j({'passed':True,'controlled_requests':4,
        'external_model_requests':0,'cases':cases}),encoding='utf-8')
    await fixture.main()


if __name__=='__main__':asyncio.run(main())
