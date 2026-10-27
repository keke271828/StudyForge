"""Fresh-process acceptance, deliberately restricted to explicitly isolated data."""
import asyncio
import json
import os
import sys
from unittest.mock import patch

if not os.environ.get('STUDYFORGE_DATA_DIR'):raise SystemExit('Explicit isolated STUDYFORGE_DATA_DIR required')

from studyforge import server
from studyforge.db import many,one
from tests.test_homework import Teacher,finish


async def main():
    teacher=Teacher(unknown=False)
    before=many('SELECT * FROM mastery ORDER BY topic')
    with patch.object(server,'client_for',lambda *a,**kw:teacher):
        accepted=await server.homework_retry(sys.argv[1],sys.argv[2])
        task=await finish(accepted)
    proof={'status':task['status'],'mastery_unchanged':many('SELECT * FROM mastery ORDER BY topic')==before,
        'submissions':one('SELECT COUNT(*) AS n FROM submissions')['n'],'model_calls':len(teacher.calls),
        'grading_calls':sum('批改者' in system or '编程教师' in system for system,_ in teacher.calls)}
    print(json.dumps(proof,ensure_ascii=False))
    if task['status']!='completed':raise SystemExit(task['error'])


if __name__=='__main__':asyncio.run(main())
