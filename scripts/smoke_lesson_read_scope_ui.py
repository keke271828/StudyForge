"""Numbered AI heading must not choose an original PDF page in either UI."""
import asyncio
import json

import fitz

from scripts import smoke_content_rounds_ui as rounds
from studyforge import lesson_feedback, server
from studyforge.db import create_job, execute, now, one, uid

fixture = rounds.fixture
rounds.native.DRAFT = rounds.native.DRAFT.replace('# 统一门槛的选择', '# 第2章的讲解')


async def respond(request):
    if not rounds.generating and request.method != 'GET':
        packet = json.loads(request.content)
        text = json.dumps(packet, ensure_ascii=False)
        assert 'SOURCE_FIRST_PAGE_ASSUMPTIONS' in text and 'SOURCE_SECOND_PAGE_CONCLUSION' in text
        assert '请先明确选段' not in text
    return await rounds.respond(request)


fixture.respond = respond


async def main():
    source = fixture.case_path.parent / 'original.pdf'
    with fitz.open() as document:
        for text in ('SOURCE_FIRST_PAGE_ASSUMPTIONS: n must exceed both N1 and N2.',
                     'SOURCE_SECOND_PAGE_CONCLUSION: N=max(N1,N2) or any larger N is sufficient.'):
            page = document.new_page()
            page.insert_text((50,80), text)
        document.save(source)
    sid = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (sid,fixture.p['id'],source.name,'.pdf',str(source),'ready',now()))
    value = server.GenerateIn(project_id=fixture.p['id'],conversation_id=fixture.c['id'],source_ids=[sid],
        provider='deepseek',model='fixture-writer',generation_quality='custom',review_mode='fast',format='docx',exercises=False)
    job = create_job(fixture.p['id'],'generate',value.model_dump())
    await server._generate_job(job,value)
    assert one('SELECT status FROM jobs WHERE id=?',(job,))['status'] == 'completed'
    root = lesson_feedback.ensure_questionnaire(job)
    lesson_feedback.submit_questionnaire(root['id'],[],'',skip=True)
    rounds.generating = False
    fixture.case.update(root_feedback_id=root['id'],artifact_id=root['artifact_id'],native_requests=2,
        scope_case='AI heading 第2章 must not override original PDF scope',source_id=sid)
    assert len(fixture.calls) == 2
    await fixture.main()


if __name__ == '__main__': asyncio.run(main())
