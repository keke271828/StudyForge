"""Replay saved real review text through strict decode and actual DOCX jobs."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


async def main():
    out=ROOT/'build'/sys.argv[1]
    if out.exists():raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True);os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    from studyforge import ai,conversations,server
    from studyforge.db import create_job,create_project,execute,j,many,now,one,uid,unj
    from docx import Document
    from lxml import etree
    import httpx
    ai.save_settings({'chat_provider':'deepseek','deepseek_model':'replay-only','agent_tools_enabled':False,
        'background_learning_enabled':False,'model_concurrency':2})
    decoded=[]
    for number in (1,2):
        folder=ROOT/'build'/f'algebra-witness-review-live-20261021-{number}'
        inputs=json.loads((folder/'inputs.json').read_text(encoding='utf-8'))
        for case in inputs:
            file=case['name']+'-'+case['arm']+'.json';raw=(folder/file).read_text(encoding='utf-8')
            try:json.loads(raw);strict=True
            except json.JSONDecodeError:strict=False
            value=ai.parse_json_response(raw)
            row={'experiment':number,'case':case['name'],'arm':case['arm'],'strict_json':strict,
                 'parsed_with_literal_delimiters':True,'passed':value['passed'],'issues':value['issues'],
                 'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'raw_file':str((folder/file).relative_to(ROOT/'build'))}
            decoded.append(row)
    final_inputs=json.loads((ROOT/'build/algebra-witness-review-live-20261021-2/inputs.json').read_text(encoding='utf-8'))
    jobs=[]
    for case in final_inputs:
        key=case['name']+'-'+case['arm'];folder=ROOT/'build/algebra-witness-review-live-20261021-2'
        raw=(folder/(key+'.json')).read_text(encoding='utf-8');project=create_project('回放 '+key)
        chat=conversations.create(project['id'],'deepseek');path=out/(key+'-source.txt');path.write_text(case['source'],encoding='utf-8');sid=uid()
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (sid,project['id'],path.name,'.txt',str(path),'ready',now()))
        calls=[]
        def respond(request):
            body=json.loads(request.content);calls.append(copy.deepcopy(body))
            answer=raw if body.get('response_format',{}).get('type')=='json_object' else case['document']
            return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
        original=httpx.AsyncClient
        with patch.object(ai,'get_secret',lambda key:'controlled-replay-only'),patch.object(httpx,'AsyncClient',lambda *a,**k:original(transport=httpx.MockTransport(respond))):
            value=server.GenerateIn(project_id=project['id'],conversation_id=chat['id'],source_ids=[sid],provider='deepseek',
                model='replay-only',format='docx',exercises=False,review_mode='fast',explanation_style='balanced')
            job=create_job(project['id'],'generate',value.model_dump());await server._generate_job(job,value)
        state=one('SELECT * FROM jobs WHERE id=?',(job,));assert state['status']=='completed',state['error']
        assert len(calls)==2,'Only one controlled draft plus the saved review, no cloud or format re-request.'
        artifact=one("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(project['id'],))
        snapshot=one('SELECT * FROM document_snapshots WHERE job_id=?',(job,))
        word=Document(artifact['path']);xml_text=''.join(etree.fromstring(word.part.blob).xpath('//*[local-name()="t"]/text()'))
        dest=out/(key+'.docx');dest.write_bytes(Path(artifact['path']).read_bytes())
        reports=unj(snapshot['metadata_json'])['reviews'];assert reports
        if case['name']=='unconditional' and case['arm']=='fixed':
            assert reports[0].get('locally_corrected_issues')
        elif case['name']=='unconditional':
            # This real baseline found both errors but proposed no corrections.
            # Preserve the draft and unresolved concerns, never invent edits.
            assert not reports[0].get('locally_corrected_issues') and '待核实事项' in snapshot['content']
        else:
            assert not reports[0].get('locally_corrected_issues')
            assert case['document'].split('## 系统性总结',1)[0].rstrip() in snapshot['content']
            assert snapshot['content'].endswith(case['document'].split('## 系统性总结',1)[1].strip())
        row={'case':case['name'],'arm':case['arm'],'docx':dest.name,'controlled_model_requests':len(calls),
             'review_passed':reports[0]['passed'],'locally_corrected_issues':reports[0].get('locally_corrected_issues',[]),
             'conditional_warning_retained':'局部代数核对提示' in snapshot['content'],
             'content':snapshot['content'],'word_text':xml_text,'reviews':reports,
             'docx_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
        jobs.append(row)
    assert not many('SELECT * FROM mastery') and not many('SELECT * FROM exercise_sets')
    result={'passed':True,'decoded':decoded,'jobs':jobs,'actual_cloud_requests':0,'controlled_model_requests':8,
            'learner_mastery_writes':0,'private_exercises_created':0,'docx_layout_rendered':False}
    (out/'report.json').write_text(j(result),encoding='utf-8');print(j({k:v for k,v in result.items() if k not in ('decoded','jobs')}))


if __name__=='__main__':asyncio.run(main())
