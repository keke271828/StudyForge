"""Two native explanation jobs and real desktop/paired HTTPS UI, isolated AI."""
import asyncio

import httpx

from scripts import smoke_library_ui as fixture
from studyforge import server
from studyforge.db import create_job, execute, j, many, now, one, uid, unj

fixture.enable_semantic(False)
DRAFT = '# 统一门槛的选择\n\n门槛必须且只能取N=max{N1,N2}，更大的N均不可用。\n\n## 对照原条件\n\n题目限定同一个n满足两个下界。[来源：第1页]\n\n## 系统性总结\n\n先统一门槛，再使用两条估计。'
REPORT = {'passed': False, 'issues': [
    {'location': '统一门槛的选择', 'problem': '把常用构造说成唯一选择', 'evidence': 'N更大仍保证n超过两个门槛。'},
    {'location': '来源定位', 'problem': '需对照实际页码核对来源', 'evidence': '核查意见本身不是原文件。'}],
    'corrections': [
        {'issue_index': 0, 'before': '门槛必须且只能取N=max{N1,N2}，更大的N均不可用。',
         'after': '为保证n同时超过N1与N2，可以取N=max{N1,N2}，也可以取更大的N。'},
        {'issue_index': 1, 'before': '[来源：第1页]', 'after': '[来源：第2页]'}]}


async def respond(request):
    if request.method == 'GET': return httpx.Response(200, json={'data': [{'id': 'fixture-writer'}]})
    import json
    payload = json.loads(request.content)
    fixture.calls.append(payload)
    answer = j(REPORT) if payload.get('response_format', {}).get('type') == 'json_object' else DRAFT
    if payload.get('stream'):
        return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': answer}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
    return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': answer}, 'finish_reason': 'stop'}]})


fixture.respond = respond


async def main():
    source = fixture.case_path.parent / '门槛原资料.txt'
    source.write_text('若n>N1且n>N2，两条估计同时成立。取N=max{N1,N2}或更大的N均可保证这两项条件。[来源：第1页]', encoding='utf-8')
    source_id = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source_id, fixture.p['id'], source.name, '.txt', str(source), 'ready', now()))
    cases = []
    for mode in ('fast', 'express'):
        value = server.GenerateIn(project_id=fixture.p['id'], conversation_id=fixture.c['id'], source_ids=[source_id],
            provider='deepseek', model='fixture-writer', generation_quality='custom', review_mode=mode, format='docx', exercises=False)
        job_id = create_job(fixture.p['id'], 'generate', value.model_dump())
        await server._generate_job(job_id, value)
        job = one('SELECT * FROM jobs WHERE id=?', (job_id,))
        assert job['status'] == 'completed', job['error']
        artifact = next(row for row in many('SELECT * FROM artifacts WHERE project_id=?', (fixture.p['id'],))
                        if unj(row['metadata_json'], {}).get('generation_job_id') == job_id)
        meta = unj(artifact['metadata_json'])
        if mode == 'fast':
            assert meta['reviews'][0]['locally_corrected_issues'] == [0]
            assert len(meta['reviews'][0]['local_correction_anchors']) == 1
        cases.append({'mode': mode, 'artifact_id': artifact['id'], 'job_id': job_id, 'metadata': meta})
    assert len(fixture.calls) == 3
    assert not many('SELECT * FROM learning_events')
    fixture.case.update(teaching_review_cases=cases, model_requests=3)
    (fixture.case_path.parent / 'native-results.json').write_text(j({'passed': True, 'cases': cases,
        'controlled_requests': 3, 'external_model_requests': 0, 'learning_events': 0}), encoding='utf-8')
    await fixture.main()


if __name__ == '__main__': asyncio.run(main())
