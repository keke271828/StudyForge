import base64
import json

import pytest
from fastapi.testclient import TestClient

from studyforge import conversations, db, message_history, server
from studyforge.db import connect, create_project, execute, uid


def history(count=155):
    p=create_project('分页项目');c=conversations.create(p['id'],'deepseek');ids=[]
    with connect() as database:
        for i in range(count):
            ident=uid();ids.append(ident)
            database.execute('INSERT INTO messages VALUES (?,?,?,?,?)',
                (ident,c['id'],'user' if i%2==0 else 'assistant',f'完整记录 {i}', '2026-10-11T00:00:00+00:00'))
    return p,c,ids


def test_all_pages_keep_tied_timestamp_order_without_duplicates():
    p,c,ids=history();collected=[];before=None
    while True:
        part=message_history.page(c['id'],p['id'],limit=60,before=before)
        assert len(part['messages'])<=60
        collected=[r['id'] for r in part['messages']]+collected
        if not part['history']['has_older']:break
        before=part['history']['oldest_cursor']
    assert collected==ids
    assert len(conversations.detail(c['id'],p['id'])['messages'])==155
    client=TestClient(server.app)
    assert len(client.get(f"/api/conversations/{c['id']}/messages?project_id={p['id']}").json()['messages'])==155
    assert len(client.get(f"/api/conversations/{c['id']}?project_id={p['id']}&history_limit=60").json()['messages'])==60


def test_unchanged_reply_is_small_and_edits_deletions_are_visible():
    p,c,ids=history();first=message_history.page(c['id'],p['id'],limit=60)
    revision=first['history']['revision'];anchor=first['history']['oldest_cursor']
    unchanged=message_history.page(c['id'],p['id'],limit=60,start=anchor,since=revision)
    assert unchanged['not_modified'] and 'messages' not in unchanged and len(json.dumps(unchanged))<100
    execute('UPDATE messages SET content=? WHERE id=?',('更正同一 ID 的内容',ids[-2]))
    updated=message_history.page(c['id'],p['id'],start=anchor,since=revision)
    assert next(r for r in updated['messages'] if r['id']==ids[-2])['content']=='更正同一 ID 的内容'
    assert updated['history']['revision']>revision
    execute('DELETE FROM messages WHERE id=?',(ids[-1],))
    deleted=message_history.page(c['id'],p['id'],start=anchor,since=updated['history']['revision'])
    assert ids[-1] not in [r['id'] for r in deleted['messages']]
    execute('UPDATE messages SET content=content WHERE id=?',(ids[-2],))
    assert message_history.page(c['id'],p['id'],since=deleted['history']['revision'])['not_modified']


def test_append_keeps_the_visible_window_and_older_loading_reaches_every_message():
    p,c,ids=history();first=message_history.page(c['id'],p['id'],limit=60)
    ident=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(ident,c['id'],'assistant','独立任务结果','2026-10-12'))
    newer=message_history.page(c['id'],p['id'],start=first['history']['oldest_cursor'],since=first['history']['revision'])
    assert [r['id'] for r in newer['messages']]==ids[-60:]+[ident]
    old=message_history.page(c['id'],p['id'],before=first['history']['oldest_cursor'],limit=60)
    combined=message_history.page(c['id'],p['id'],start=old['history']['oldest_cursor'])
    assert [r['id'] for r in combined['messages']]==ids[-120:]+[ident]


def test_removing_every_visible_row_still_allows_loading_older_records():
    p,c,ids=history();first=message_history.page(c['id'],p['id'],limit=60)
    with connect() as database:database.executemany('DELETE FROM messages WHERE id=?',((ident,) for ident in ids[-60:]))
    cleared=message_history.page(c['id'],p['id'],start=first['history']['oldest_cursor'])
    assert not cleared['messages'] and cleared['history']['has_older']
    older=message_history.page(c['id'],p['id'],before=cleared['history']['oldest_cursor'],limit=60)
    assert [r['id'] for r in older['messages']]==ids[35:95]


def test_cross_scope_cursors_and_project_mismatches_are_rejected():
    p,c,_=history();q,d,_=history();token=message_history.page(d['id'],q['id'],limit=60)['history']['oldest_cursor']
    client=TestClient(server.app);base=f"/api/conversations/{c['id']}/messages?project_id={p['id']}&limit=60"
    assert client.get(base+'&before='+token).status_code==400
    assert client.get(f"/api/conversations/{c['id']}/messages?project_id={q['id']}&limit=60").status_code==404
    for suffix in ('&before=not-a-cursor','&since=-1','&before='+token+'&start='+token):
        assert client.get(base+suffix).status_code==400


def test_cursor_validation_and_page_limits():
    p,c,_=history(3)
    for data in ([c['id'],'date',True],[c['id'],'date',0],{'wrong':'type'}):
        value=base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
        with pytest.raises(ValueError):message_history.page(c['id'],p['id'],before=value,limit=60)
    for limit in (0,201):
        with pytest.raises(ValueError):message_history.page(c['id'],p['id'],limit=limit)


def test_moving_a_message_updates_both_conversation_versions():
    p,c,ids=history(3);d=conversations.create(p['id'],'deepseek')
    a=message_history.page(c['id'],p['id']);b=message_history.page(d['id'],p['id'])
    execute('UPDATE messages SET conversation_id=? WHERE id=?',(d['id'],ids[-1]))
    assert not message_history.page(c['id'],p['id'],since=a['history']['revision'])['not_modified']
    assert message_history.page(d['id'],p['id'],since=b['history']['revision'])['messages'][0]['id']==ids[-1]


def test_legacy_upgrade_keeps_messages_and_tracks_future_mutations(monkeypatch):
    p,c,ids=history(3)
    with connect() as database:
        for name in ('history_message_insert','history_message_delete','history_message_update'):
            database.execute('DROP TRIGGER '+name)
        database.execute('DROP TABLE conversation_history_versions')
    monkeypatch.setattr(db,'_initialized_databases',{})
    upgraded=message_history.page(c['id'],p['id'],limit=60)
    assert [r['id'] for r in upgraded['messages']]==ids
    assert upgraded['history']['revision']==0
    execute('UPDATE messages SET content=? WHERE id=?',('迁移后更正',ids[-1]))
    assert message_history.page(c['id'],p['id'],since=0)['history']['revision']==1


def test_setting_save_can_omit_display_history_without_changing_model_history():
    p,c,ids=history();client=TestClient(server.app)
    response=client.put(f"/api/conversations/{c['id']}?include_history=false",
        json={'project_id':p['id'],'draft':'未发送的问题'})
    assert response.status_code==200,response.text
    assert response.json()['history_omitted'] and response.json()['messages']==[]
    full=conversations.detail(c['id'],p['id'])
    assert full['draft']=='未发送的问题' and [r['id'] for r in full['messages']]==ids
    assert [r['id'] for r in server.conversation_history(c['id'],p['id'],[])]==ids
