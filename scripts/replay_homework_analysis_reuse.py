"""Persist and resume saved real teaching in separate processes, without a cloud call."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/'build/homework-analysis-reuse-live-20261022-1'


async def main():
    out=ROOT/'build'/sys.argv[1];phase=sys.argv[2]
    if phase not in ('prepare','baseline','resume'):raise SystemExit('Unknown phase.')
    dest=out/phase
    if dest.exists():raise SystemExit('Preserve earlier replay; use a fresh folder.')
    dest.mkdir(parents=True);os.environ['STUDYFORGE_DATA_DIR']=str(dest/'data')
    from studyforge import homework
    from studyforge.db import j
    from studyforge.exporters import export_document
    from studyforge.document_render import inline_parts
    from docx import Document
    from lxml import etree
    scenario=json.loads((LIVE/'scenario.json').read_text(encoding='utf-8'))
    row=scenario['row'];worksheet=scenario['worksheet'];grade=scenario['grade']
    arm={'prepare':'initial','baseline':'baseline','resume':'fixed'}[phase]
    raw=(LIVE/(arm+'-raw-1.json')).read_text(encoding='utf-8')
    if phase!='prepare':row=json.loads((out/'state.json').read_text(encoding='utf-8'))
    calls=[]
    class Client:
        provider='deepseek';model='deepseek-flash';effort='high'
        async def complete(self,system,user,**kwargs):
            calls.append({'system':system,'user':user})
            assert len(calls)==1,'Replay must not create a format repair or another result.'
            expected=json.loads((LIVE/(arm+'-request-1.json')).read_text(encoding='utf-8'))
            assert expected['messages'][0]['content']==system
            assert expected['messages'][-1]['content']==user
            return raw
    operation=homework.analyze
    if phase=='baseline':
        ns={'__name__':'studyforge.old_homework','__package__':'studyforge'}
        path=ROOT/'build/homework-analysis-reuse-20261022/baseline-homework.py'
        exec(compile(path.read_text(encoding='utf-8'),str(path),'exec'),ns);operation=ns['analyze']
    result=await operation(Client(),row,worksheet,grade,scenario['prior_causes'] if phase=='prepare' else scenario['current_causes'])
    if phase=='prepare':
        assert result['items']==json.loads((LIVE/'initial-analysis.json').read_text(encoding='utf-8'))['items']
        row['analysis_json']=j(result);(out/'state.json').write_text(j(row),encoding='utf-8')
    if phase=='resume':
        assert result['analysis_reuse']['requested_indices']==[0] and result['analysis_reuse']['reused_indices']==[1,2]
        previous=json.loads(row['analysis_json'])
        assert result['items'][1:]==previous['items'][1:]
    report={'passed':True,'phase':phase,'process_id':os.getpid(),'controlled_model_requests':len(calls),'external_model_requests':0,
        'requested_indices':json.loads(calls[0]['user'])['wrong_indices'],'analysis':result,'prompts_match_actual_sample':True,
        'state_sha256':hashlib.sha256((out/'state.json').read_bytes()).hexdigest()}
    if phase!='prepare':
        content=homework.report_document(row,worksheet,grade,result)
        title='澄清后_'+('整套重新生成' if phase=='baseline' else '按题续做')+'_批改与错题讲解'
        exported=export_document(content,'docx',title,title+'.docx');target=dest/(title+'.docx');target.write_bytes(exported.read_bytes())
        words=Document(target);text=''.join(etree.fromstring(words.part.blob).xpath('//*[local-name()="t"]/text()'))
        assert all(question['question'] in text for question in json.loads(worksheet['questions_json']))
        # DOCX formulas become native OMML, so literal Markdown/LaTeX is not
        # expected in its XML text. Verify the unchanged prose pieces instead.
        for item in result['items']:
            for kind,value in inline_parts(item['cause']):
                if kind in ('text','bold') and len(value.strip())>3:assert value.strip() in text
        assert all(len(item['explanation'])>=40 for item in result['items'])
        (dest/'最终讲解.md').write_text(content,encoding='utf-8')
        report.update(docx_file=target.name,content=content,docx_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),docx_layout_rendered=False)
    (dest/'report.json').write_text(j(report),encoding='utf-8')
    print(j({key:report[key] for key in ('passed','phase','process_id','requested_indices','controlled_model_requests','external_model_requests')}))


if __name__=='__main__':asyncio.run(main())
