"""Actual tutor answer -> local export on desktop and paired HTTPS phone."""
import asyncio
import hashlib
import os
from pathlib import Path
import sys

folder=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
from scripts import smoke_library_ui as fixture
from studyforge.db import execute,now,uid
from studyforge.message_exports import STOPPED

fixture.enable_semantic(False)
answer=(fixture.root/'build/compact-teaching-real-20261016-1/code_copy-compact-final.md').read_text(encoding='utf-8')
mid,student,stopped=uid(),uid(),uid()
execute('INSERT INTO messages VALUES (?,?,?,?,?)',(student,fixture.c['id'],'user','请针对浅复制的两次修改解释。',now()))
execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,fixture.c['id'],'assistant',answer,now()))
execute('INSERT INTO messages VALUES (?,?,?,?,?)',(stopped,fixture.c['id'],'assistant','未完成内容\n'+STOPPED,now()))
fixture.case.update(message_id=mid,student_message_id=student,stopped_message_id=stopped,answer_sha256=hashlib.sha256(answer.encode()).hexdigest(),
    answer_characters=len(answer),process_id=os.getpid())

if __name__=='__main__':asyncio.run(fixture.main())
