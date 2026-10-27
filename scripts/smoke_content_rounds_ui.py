"""Native explanation then repeatable content checks through both real UIs."""
import asyncio
import json

import httpx

from scripts import smoke_teaching_review_ui as native
from studyforge import lesson_feedback, server
from studyforge.db import create_job, execute, j, many, now, one, uid, unj

fixture = native.fixture
generating = True


async def respond(request):
    if generating or request.method == 'GET': return await native.respond(request)
    payload = json.loads(request.content)
    fixture.calls.append(payload)
    answer = '# 核对统一门槛\n\n取最大值是方便的充分构造，不是唯一允许的选择。若N1=5、N2=8，取N=10且n>10，当然同时保证n>5和n>8。\n\n## 小结\n\n保证两项下标条件即可；更大的N依然可用。此处只核对讲解，没有布置习题。'
    return httpx.Response(200, text='data: ' + j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]}) + '\n\ndata: [DONE]\n\n')


fixture.respond = respond


@server.app.get('/__content_rounds_test__/state')
def state():
    return {'requests':len(fixture.calls), 'learning_events':len(many('SELECT * FROM learning_events')),
            'learning_insights':len(many('SELECT * FROM learning_insights')), 'mastery':len(many('SELECT * FROM mastery')),
            'jobs':len(many('SELECT * FROM jobs')), 'exercises':len(many('SELECT * FROM exercise_sets'))}


mount = next(route for route in server.app.routes if getattr(route, 'name', None) == 'web')
server.app.router.routes.remove(mount)
server.app.router.routes.append(mount)


async def main():
    global generating
    source = fixture.case_path.parent / '门槛原资料.txt'
    source.write_text('若n>N1且n>N2，两条估计同时成立。取N=max{N1,N2}或更大的N均可保证这两项条件。[来源：第1页]', encoding='utf-8')
    source_id = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source_id, fixture.p['id'], source.name, '.txt', str(source), 'ready', now()))
    value = server.GenerateIn(project_id=fixture.p['id'], conversation_id=fixture.c['id'], source_ids=[source_id],
        provider='deepseek', model='fixture-writer', generation_quality='custom', review_mode='fast', format='docx', exercises=False)
    job = create_job(fixture.p['id'], 'generate', value.model_dump())
    await server._generate_job(job, value)
    assert one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'completed'
    root = lesson_feedback.ensure_questionnaire(job)
    lesson_feedback.submit_questionnaire(root['id'], [], '', skip=True)
    generating = False
    fixture.case.update(root_feedback_id=root['id'], artifact_id=root['artifact_id'], native_requests=2)
    assert len(fixture.calls) == 2
    await fixture.main()


if __name__ == '__main__': asyncio.run(main())
