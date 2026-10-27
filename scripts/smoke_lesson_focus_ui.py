"""Actual desktop and paired HTTPS phone exercise optional lesson locations.

All data is synthetic and isolated; only model transport is mocked. Export,
questionnaires, profile records, persistence and the two interfaces are real.
"""
import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / 'build' / sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(CASE / 'isolated-model')
from scripts import smoke_library_ui as fixture
from studyforge import conversations, lesson_feedback, server
from studyforge.db import create_job, execute, j, now, uid
from studyforge.exporters import export_document

fixture.enable_semantic(False)
second = conversations.create(fixture.p['id'], 'deepseek', 'deepseek-flash')


def seed(chat, title, document):
    job = create_job(fixture.p['id'], 'generate', {'source_ids': [], 'conversation_id': chat['id'],
        'learning_mode': 'deep', 'explanation_style': 'balanced', 'output_language': 'zh'})
    path = export_document(document, 'docx', title, job + '.docx')
    artifact = server.add_artifact(fixture.p['id'], [], 'explanation', 'docx', title, path,
                                  {'generation_job_id': job, 'conversation_id': chat['id']})
    message = uid()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (message, chat['id'], 'assistant', '已生成讲解文档：\n\n' + document, now()))
    execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)', (job, chat['id'], message))
    execute("UPDATE jobs SET status='completed' WHERE id=?", (job,))
    return dict(lesson_feedback.ensure_questionnaire(job), artifact=artifact)


old = seed(fixture.c, '极限为什么唯一', '# 极限为什么唯一\n\n## 怎样想到取距离的一半\n\nFOCUS_OLD_MARKER：两个极限有正距离，定义允许任意正半径；取一半时，开邻域排除共同中点。\n\n## 怎样统一两个门槛\n\n取两个门槛的最大值，保证条件同时满足。')
newer = seed(fixture.c, '后来生成的另一讲解', '# NEWER_DOCUMENT_MARKER\n\n## 完全不同的章节\n\n新的内容保留在同一对话，但不是旧问卷的补讲目标。')
phone = seed(second, '为什么参数需要可调', '# 为什么参数需要可调\n\n## 单点非负与恒非负有什么差别\n\nFOCUS_PHONE_MARKER：只取一个参数值只知道一个点上的值；任意参数才能约束整个二次函数。\n\n## 如何连接到最小值\n\n配方时保持非零条件，解释最小值所能提供的限制。')
conversations.activate(fixture.c['id'])
fixture.case.update(old_questionnaire=old, new_questionnaire=newer, phone_questionnaire=phone,
                    phone_conversation_id=second['id'], process_id=os.getpid())

if __name__ == '__main__': asyncio.run(fixture.main())
