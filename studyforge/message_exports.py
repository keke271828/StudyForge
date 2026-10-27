"""Freeze an already public tutor answer for local export, without AI rewriting."""
from __future__ import annotations

import hashlib

from .db import connect,j,now,uid,unj
from .document_exports import FORMATS
from .navigation import require_project,title as checked_title

STOPPED='[本次回复已停止，以上内容尚未完成。]'


def launch(project_id,conversation_id,message_id,fmt,request_id,content_sha256,title=''):
    if fmt not in FORMATS:raise ValueError('请选择支持的本机排版格式')
    require_project(project_id)
    from .document_render import validate_document_text
    from .mobile_context import remote_device
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT m.*,c.provider FROM messages m JOIN conversations c ON c.id=m.conversation_id '
            'WHERE m.id=? AND m.conversation_id=? AND c.project_id=? AND NOT EXISTS '
            '(SELECT 1 FROM deleted_conversations d WHERE d.conversation_id=c.id)',
            (message_id,conversation_id,project_id)).fetchone()
        if not row:raise LookupError('这条回答不属于当前项目和对话，或已删除')
        if row['role']!='assistant':raise ValueError('此入口只保存已经公开的导师回答')
        content=row['content']
        if not content.strip() or content.rstrip().endswith(STOPPED):raise ValueError('这条回答尚未完整完成，请选择已完成的导师回答')
        digest=hashlib.sha256(content.encode('utf-8')).hexdigest()
        if digest!=content_sha256:raise ValueError('这条回答内容已变化，请刷新对话后重新保存')
        validate_document_text(content)
        label=checked_title(title or '导师回答 · '+row['created_at'][:10])
        spec={'message_id':message_id,'conversation_id':conversation_id,'content_sha256':digest,'format':fmt,'title':label}
        prior=db.execute("SELECT id,payload_json FROM jobs WHERE project_id=? AND kind='export' "
            "AND json_extract(payload_json,'$.export_request_id')=?",(project_id,request_id)).fetchone()
        if prior:
            if unj(prior['payload_json']).get('message_export_spec')!=spec:raise ValueError('同一次保存请求的回答、标题或格式已改变，请重新发起')
            return prior['id'],True
        for prior in db.execute("SELECT id,payload_json FROM jobs WHERE project_id=? AND kind='export' "
                "AND status IN ('queued','running','pausing','paused')",(project_id,)).fetchall():
            if unj(prior['payload_json']).get('message_export_spec')==spec:return prior['id'],True
        ident=uid();stamp=now()
        metadata={'conversation_id':conversation_id,'provider':row['provider'],'model':'原回答模型未记录',
            'source_reading':[], 'chat_export':{'message_id':message_id,'conversation_id':conversation_id,
                'content_sha256':digest,'message_created_at':row['created_at'],'model_requests':0,'reviewed_again':False,
                'content_characters':len(content),
                'basis':'已公开导师回答原样保存；未重新核查原资料，不推定后来选择的模型或资料是本回答的依据'}}
        values={'document_id':ident,'content_sha256':digest,'format':fmt,'title':label,
            'source_artifact_id':None,'source_metadata':{},'origin_message_id':message_id}
        payload={'workflow_version':1,'values':values,'export_request_id':request_id,
            'conversation_id':conversation_id,'message_export_spec':spec}
        if remote_device.get():payload['_mobile_device_id']=remote_device.get()
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,project_id,'export','queued',0,j(payload),'{}',None,stamp,stamp))
        # The export owns its snapshot. No fake generation job, duplicate public
        # reply, new learner observation, or model client is needed.
        db.execute('INSERT INTO document_snapshots VALUES (?,?,?,?,?,?,?,?)',
            (ident,project_id,label,content,digest,'[]',j(metadata),stamp))
    return ident,False
