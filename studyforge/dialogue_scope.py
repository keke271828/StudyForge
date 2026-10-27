"""Identity and visibility boundaries for learning dialogues and tool state."""
from .db import one


CONTEXT_BOUNDARY = (
    '\n【本次对话与学习画像的可见范围】\n'
    '只接收当前学习对话的公开消息、当前明确选中的项目资料和当前对话的工具结果。'
    '同项目的其他对话、其他项目的聊天原文、内部工具历史与工作目录均隔离，不能自主读取或列举。'
    '跨项目共享的是学习画像摘要：已接触知识、做题/费曼/自评分开记录、暂定困难和明确教学偏好；'
    '这不代表看过产生画像的聊天记录，也不能凭画像重建或编造其他对话原文。'
    '需要查看画像时使用提供的摘要或 sf_read_learning_profile，只陈述实际返回的记录；'
    '摘要为空时说明目前没有可用记录，不声称软件永远无法提供画像。'
    '之前的助手若声称能读取其他对话，以本次实际权限为准，不能沿用未经工具证实的访问声明。'
    '用户自行将材料或成果选入当前对话时，可以读取所选资料；这不开放它的来源聊天记录。\n'
)


def validate_conversation(conversation_id, project_id=None):
    if not conversation_id:return None
    row=one('SELECT id,project_id FROM conversations WHERE id=?',(conversation_id,))
    if not row or one('SELECT 1 FROM deleted_conversations WHERE conversation_id=?',(conversation_id,)):
        raise ValueError('学习对话不存在或已删除')
    if project_id is not None and row['project_id']!=project_id:
        raise PermissionError('学习对话不属于当前项目，不能读取它的上下文')
    from .navigation import require_project
    require_project(row['project_id'])
    return row


def validate_client(runtime, conversation):
    if not conversation:return
    if not conversation.get('id'):raise ValueError('模型会话缺少学习对话 ID')
    row=validate_conversation(conversation.get('id'),getattr(runtime,'project_id',None))
    if runtime and not runtime.private_context and runtime.conversation_id!=row['id']:
        raise PermissionError('模型会话与当前学习对话不匹配，已阻止加载历史')


def retain_public_annotation(database, conversation_id, original, annotated):
    """Keep provider replay consistent with the locally annotated public reply."""
    from .db import j, unj
    saved = database.execute('SELECT messages_json FROM agent_dialogue_state WHERE conversation_id=?',
                             (conversation_id,)).fetchone()
    messages = unj(saved['messages_json'], []) if saved else []
    if (isinstance(messages,list) and messages and isinstance(messages[-1],dict) and messages[-1].get('role')=='assistant'
            and messages[-1].get('content')==original and not messages[-1].get('tool_calls')):
        messages[-1]['content'] = annotated
        database.execute('UPDATE agent_dialogue_state SET messages_json=? WHERE conversation_id=?',
                         (j(messages),conversation_id))
    elif saved:
        database.execute('DELETE FROM agent_dialogue_state WHERE conversation_id=?',(conversation_id,))
        database.execute('DELETE FROM agent_dialogue_scopes WHERE conversation_id=?',(conversation_id,))
    # Native remote threads cannot amend a delivered assistant message. Rebuild
    # those from public history next turn, rather than hide the local notice.
    database.execute('UPDATE conversations SET remote_thread_id=NULL WHERE id=?',(conversation_id,))
