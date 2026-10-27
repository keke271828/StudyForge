import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studyforge import conversations,server
from studyforge.ai import save_settings
from studyforge.agent_tools import AgentRuntime
from studyforge.agent_permissions import decide,list_requests
from studyforge.db import create_project,create_job,many,one,execute


@pytest.fixture(autouse=True)
def isolate_application_root(tmp_path,monkeypatch):
    # pytest's temp files live below the real code workspace, which is an
    # explicitly authorized root. External-file cases need an independent root.
    from studyforge import agent_permissions
    monkeypatch.setattr(agent_permissions,'application_root',lambda:tmp_path/'application')


def runtime():
    project=create_project('权限验收');chat=conversations.create(project['id'],'deepseek')
    return AgentRuntime(project['id'],conversation_id=chat['id'],on_event=lambda event:None)


async def pending(r):
    for _ in range(100):
        rows=list_requests(r.project_id,r.conversation_id)
        if rows:return rows[0]
        await asyncio.sleep(.02)
    raise AssertionError('No approval was created')


def test_readonly_prevents_all_publishing_and_file_mutations(tmp_path):
    r=runtime();file=r.workspace/'lesson.txt';file.write_text('原内容',encoding='utf-8')
    save_settings({'agent_permission_mode':'read_only'})
    cases=[('sf_write_text',{'path':str(file),'text':'覆盖','overwrite':True}),
           ('sf_edit_text',{'path':str(file),'old':'原内容','new':'覆盖'}),
           ('sf_delete_file',{'path':str(file)}),('sf_copy_file',{'source':str(file),'destination':'copy.txt'}),
           ('sf_create_document',{'title':'讲解','content':'不能输出','format':'docx'}),('sf_generate_image',{'prompt':'test'})]
    for tool,args in cases:assert '只读模式' in asyncio.run(r.execute(tool,args))['error']
    assert file.read_text(encoding='utf-8')=='原内容' and not (r.workspace/'copy.txt').exists()
    assert not many('SELECT * FROM agent_approvals')


def test_full_access_can_modify_delete_restore_and_read_arbitrary_binary(tmp_path):
    save_settings({'agent_permission_mode':'full_access'})
    r=runtime();file=tmp_path/'outside.txt';file.write_text('before',encoding='utf-8')
    result=asyncio.run(r.execute('sf_edit_text',{'path':str(file),'old':'before','new':'after'}))
    assert 'error' not in result and file.read_text()=='after'
    deleted=asyncio.run(r.execute('sf_delete_file',{'path':str(file)}));assert deleted['deleted'] and not file.exists()
    assert Path(deleted['backup']).read_text()=='after'
    restored=asyncio.run(r.execute('sf_copy_file',{'source':deleted['backup'],'destination':str(file)}))
    assert 'error' not in restored and file.read_text()=='after'
    binary=tmp_path/'arbitrary.bin';binary.write_bytes(b'\x00\x01\xff\x00')
    read=asyncio.run(r.execute('sf_read_file',{'path':str(binary)}));assert read['method']=='binary_bytes' and read['total_bytes']==4
    context=json.loads(r.context());assert context['history_scope']=='current_conversation_only' and context['other_chat_history_injected'] is False
    folder=tmp_path/'important';folder.mkdir();(folder/'keep.txt').write_text('keep')
    assert '非空' in asyncio.run(r.execute('sf_delete_file',{'path':str(folder)}))['error']
    save_settings({'agent_file_write_enabled':False})
    assert '关闭' in asyncio.run(r.execute('sf_delete_file',{'path':str(file)}))['error'] and file.exists()


def test_single_operation_approval_waits_and_cannot_be_used_by_other_chat(tmp_path):
    async def check():
        r=runtime();file=tmp_path/'outside.txt';file.write_text('before',encoding='utf-8')
        args={'path':str(file),'old':'before','new':'after'}
        task=asyncio.create_task(r.execute('sf_edit_text',args));row=await pending(r)
        assert not task.done() and file.read_text()=='before'
        foreign=conversations.create(r.project_id,'deepseek')
        with pytest.raises(PermissionError):decide(row['id'],r.project_id,foreign['id'],True)
        decide(row['id'],r.project_id,r.conversation_id,True)
        with pytest.raises(ValueError):decide(row['id'],r.project_id,r.conversation_id,True)
        result=await asyncio.wait_for(task,3);assert 'error' not in result and file.read_text()=='after'
        assert one('SELECT status FROM agent_approvals WHERE id=?',(row['id'],))['status']=='consumed' and not r.operation_grants
        task=asyncio.create_task(r.execute('sf_write_text',{'path':str(file),'text':'never','overwrite':True}))
        second=await pending(r);decide(second['id'],r.project_id,r.conversation_id,False)
        assert '被拒绝' in (await asyncio.wait_for(task,3))['error'] and file.read_text()=='after'
    asyncio.run(check())


@pytest.mark.parametrize('action',['change_file','read_only','cancel_job'])
def test_pending_approval_handles_changed_file_revoked_permission_and_cancel(tmp_path,action):
    async def check():
        r=runtime();file=tmp_path/'outside.txt';file.write_text('before',encoding='utf-8')
        if action=='cancel_job':r.job_id=create_job(r.project_id,'generate',{'conversation_id':r.conversation_id})
        task=asyncio.create_task(r.execute('sf_write_text',{'path':str(file),'text':'never','overwrite':True}));row=await pending(r)
        if action=='change_file':file.write_text('someone else edited',encoding='utf-8');decide(row['id'],r.project_id,r.conversation_id,True)
        elif action=='read_only':save_settings({'agent_permission_mode':'read_only'})
        else:execute("UPDATE jobs SET status='cancelled' WHERE id=?",(r.job_id,))
        if action=='cancel_job':
            with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(task,3)
        else:assert 'error' in await asyncio.wait_for(task,3)
        assert file.read_text()!='never' and not r.operation_grants
    asyncio.run(check())


def test_full_access_does_not_bypass_video_consent(tmp_path):
    save_settings({'agent_permission_mode':'full_access','agent_web_video_enabled':False})
    r=runtime();file=tmp_path/'web.mp4';file.write_bytes(b'video');r.web_paths.add(str(file))
    result=asyncio.run(r.execute('sf_read_file',{'path':str(file)}));assert '网页视频权限' in result['error']


def test_approval_api_rejects_truthy_strings_and_wrong_owner(tmp_path):
    async def check():
        r=runtime();task=asyncio.create_task(r.execute('sf_write_text',{'path':str(tmp_path/'new.txt'),'text':'allowed'}));row=await pending(r)
        client=TestClient(server.app);body={'project_id':r.project_id,'conversation_id':r.conversation_id,'approved':'false'}
        assert client.post('/api/agent/approvals/'+row['id'],json=body).status_code==422
        body['approved']=True;body['conversation_id']=conversations.create(r.project_id,'deepseek')['id']
        assert client.post('/api/agent/approvals/'+row['id'],json=body).status_code==403
        body['conversation_id']=r.conversation_id
        assert client.post('/api/agent/approvals/'+row['id'],json=body).status_code==200
        assert 'error' not in await asyncio.wait_for(task,3)
    asyncio.run(check())


def test_approved_directory_listing_only_grants_one_operation(tmp_path):
    async def check():
        r=runtime();folder=tmp_path/'external';folder.mkdir();file=folder/'read_me.txt';file.write_text('not automatically readable')
        task=asyncio.create_task(r.execute('sf_list_files',{'path':str(folder)}));row=await pending(r)
        decide(row['id'],r.project_id,r.conversation_id,True)
        result=await asyncio.wait_for(task,3);assert result['files'][0]['name']=='read_me.txt'
        with pytest.raises(PermissionError):r.checked_path(str(file))
        assert not r.operation_grants
    asyncio.run(check())
