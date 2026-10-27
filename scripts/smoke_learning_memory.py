"""One live, low-token DeepSeek memory batch; never uses the user's database."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
target = Path(tempfile.mkdtemp(prefix='learning-memory-', dir=root / 'build'))
os.environ['STUDYFORGE_DATA_DIR'] = str(target / 'data')

from studyforge.ai import save_settings
from studyforge.codex_bridge import CodexBridge
from studyforge.db import create_project, execute, j, many, now, uid, one
from studyforge.learning_memory import (MemoryWorker, discussion_completed, imported_source,
                                       reading_completed, memory_snapshot, profile_context)

async def main():
    model = os.environ.get('STUDYFORGE_SMOKE_MODEL', 'deepseek-flash')
    save_settings({'chat_provider':'deepseek','deepseek_model':model})
    project = create_project('数学学习'); philosophy = create_project('社会学阅读')
    conversation, message, source_id, reading_id = [uid() for _ in range(4)]
    path = target / 'proof.txt'; path.write_text('柯西不等式的辅助二次函数证明。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source_id, project['id'], path.name, '.txt', str(path), '[]', 'ready', now()))
    imported_source(one('SELECT * FROM sources WHERE id=?', (source_id,)))
    execute('INSERT INTO reading_sessions VALUES (?,?,?,?,?,?,?,?,?,?)',
            (reading_id, project['id'], j([source_id]), 'smoke-fingerprint', 'deepseek', model, None,
             j([{'text':'资料讨论柯西不等式，以非负二次函数构造证明；涉及判别式与零向量边界。'}]), '[]', now()))
    reading_completed(reading_id); reading_completed(reading_id)
    execute('INSERT INTO conversations(id,project_id,provider,created_at,source_ids_json,model) VALUES (?,?,?,?,?,?)',
            (conversation, project['id'], 'deepseek', now(), j([source_id]), model))
    text = '柯西不等式的二次函数证明我能跟着算，但不知道为什么想到构造这个函数。我更喜欢先讲方法的动机，再展示步骤；我对它的理解还没有经过习题检验。'
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (message, conversation, 'user', text, now()))
    discussion_completed(conversation, message); discussion_completed(conversation, message)
    async def forbidden(*args, **kwargs): raise AssertionError('DeepSeek 背景整理不能依赖 Codex')
    with patch.object(CodexBridge, 'start', forbidden):
        success = await MemoryWorker().run_once(ignore_idle=True)
    result = memory_snapshot()
    result['success'] = success
    result['mastery_unchanged'] = many('SELECT * FROM mastery') == []
    result['deduplicated_events'] = len(many('SELECT * FROM learning_events')) == 3
    result['same_model'] = one('SELECT model FROM learning_runs')['model'] == model
    result['cross_project_relevant_context'] = profile_context('另一个项目讨论柯西不等式')
    result['philosophy_context'] = profile_context('福柯与规训权力')
    (target/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    assert success and result['mastery_unchanged'] and result['deduplicated_events'] and result['same_model']
    assert any(i['kind'] in ('gap','preference') for i in result['insights'])
    assert any(i['kind'] == 'gap' for i in result['insights'])
    assert '不知道为什么' in result['cross_project_relevant_context'] or '构造' in result['cross_project_relevant_context']
    assert all(i['confidence'] == '接触记录' for i in result['insights'] if i['evidence_kind'] == 'reading')
    assert '辅助' not in result['philosophy_context'] and '柯西' not in result['philosophy_context']
    print(json.dumps({'directory':str(target), 'success':success, 'calls':result['today_calls'],
                      'insights':len(result['insights']), 'unchanged_mastery':result['mastery_unchanged']}, ensure_ascii=False))

asyncio.run(main())
