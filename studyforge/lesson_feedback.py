"""Optional source-scoped learning self reports, without AI scoring or analysis calls."""
from pathlib import Path

from .db import connect, execute, j, many, now, one, uid, unj
from .learning_memory import _save_insight
from .lesson_focus import focus_context, knowledge_anchors, public_focus, saved_focus, select_focus, selection_identity

DIFFICULTIES = [
    {'id': 'terminology', 'label': '不懂术语', 'dimension': 'concepts'},
    {'id': 'prerequisites', 'label': '缺少前置知识', 'dimension': 'concepts'},
    {'id': 'motivation', 'label': '看懂计算，但不懂构造动机', 'dimension': 'reasoning'},
    {'id': 'method_selection', 'label': '会套方法，但不知道什么时候该用', 'dimension': 'transfer'},
    {'id': 'argumentation', 'label': '能复述，却无法独立论证', 'dimension': 'expression'},
    {'id': 'implementation', 'label': '推理正确，但计算或实现出错', 'dimension': 'problem_solving'},
]
CONTENT_CHECK = {'id':'content_accuracy','label':'讲解可能有误或依据不清，请先核对','dimension':''}
OPTIONS = DIFFICULTIES + [CONTENT_CHECK]
BY_ID = {item['id']: item for item in OPTIONS}


def requests_content_check(row: dict) -> bool:
    return CONTENT_CHECK['id'] in unj(row['difficulties_json'], [])


def table_for(row: dict) -> str:
    """Only trusted stored records choose between these two fixed tables."""
    return 'lesson_content_checks' if row.get('parent_questionnaire_id') else 'lesson_questionnaires'


def available_artifact(row: dict, database=None):
    query = "SELECT id FROM artifacts WHERE id=? AND project_id=? AND kind='explanation'"
    args = (row['artifact_id'], row['project_id'])
    found = database.execute(query, args).fetchone() if database else one(query, args)
    if found: return dict(found)
    query = ("SELECT id FROM artifacts WHERE project_id=? AND kind='explanation' "
             "AND json_extract(metadata_json,'$.generation_job_id')=? ORDER BY created_at DESC LIMIT 1")
    args = (row['project_id'], row['job_id'])
    found = database.execute(query, args).fetchone() if database else one(query, args)
    return dict(found) if found else None


def create_content_check(questionnaire_id: str, project_id: str, conversation_id: str) -> dict:
    """Explicit new doubt, original source scope, one reusable pending draft."""
    original = get_questionnaire(questionnaire_id)
    if original['project_id'] != project_id or original['conversation_id'] != conversation_id:
        raise ValueError('只能在这份讲解所属的项目和原对话中继续核对')
    root_id = original.get('parent_questionnaire_id') or original['id']
    from .lesson_focus import delivered_document
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        root = database.execute('SELECT * FROM lesson_questionnaires WHERE id=? AND project_id=? AND conversation_id=?',
                                (root_id, project_id, conversation_id)).fetchone()
        if not root: raise ValueError('原理解反馈已移除，无法继续核对这份讲解')
        root = dict(root)
        artifact = available_artifact(root, database)
        if not artifact or not delivered_document(root, database):
            raise ValueError('原讲解或对应对话记录已移除，无法自动恢复核对范围')
        pending = database.execute("SELECT * FROM lesson_content_checks WHERE job_id=? AND status='pending'", (root['job_id'],)).fetchone()
        if pending: return public_questionnaire(dict(pending))
        timestamp, ident = now(), uid()
        database.execute('INSERT INTO lesson_content_checks '
            '(id,parent_questionnaire_id,job_id,project_id,conversation_id,artifact_id,title,source_ids_json,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)', (ident, root_id, root['job_id'], project_id, conversation_id,
                artifact['id'], root['title'], root['source_ids_json'], timestamp, timestamp))
        result = dict(database.execute('SELECT * FROM lesson_content_checks WHERE id=?', (ident,)).fetchone())
    return public_questionnaire(result)


def ensure_questionnaire(job_id: str) -> dict | None:
    saved = one('SELECT * FROM lesson_questionnaires WHERE job_id=?', (job_id,))
    if saved:
        if not one("SELECT 1 FROM artifacts WHERE id=? AND project_id=? AND kind='explanation'",(saved['artifact_id'],saved['project_id'])):
            replacement=one("SELECT id FROM artifacts WHERE project_id=? AND kind='explanation' "
                "AND json_extract(metadata_json,'$.generation_job_id')=? ORDER BY created_at DESC LIMIT 1",(saved['project_id'],job_id))
            if replacement:
                execute('UPDATE lesson_questionnaires SET artifact_id=? WHERE id=?',(replacement['id'],saved['id']))
                saved['artifact_id']=replacement['id']
        return public_questionnaire(saved)
    output = one('SELECT g.*,b.project_id,b.payload_json FROM generation_dialogue_outputs g '
                 'JOIN jobs b ON b.id=g.job_id WHERE g.job_id=?', (job_id,))
    artifact = one("SELECT * FROM artifacts WHERE kind='explanation' AND json_extract(metadata_json,'$.generation_job_id')=?", (job_id,))
    if not output or not artifact: return None
    payload = unj(output['payload_json'], {})
    timestamp = now()
    execute('INSERT OR IGNORE INTO lesson_questionnaires '
            '(id,job_id,project_id,conversation_id,artifact_id,title,source_ids_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (uid(), job_id, output['project_id'], output['conversation_id'], artifact['id'], artifact['title'],
             j(payload.get('source_ids', [])), timestamp, timestamp))
    return public_questionnaire(one('SELECT * FROM lesson_questionnaires WHERE job_id=?', (job_id,)))


def public_questionnaire(row: dict) -> dict:
    artifact = available_artifact(row)
    content_only = table_for(row) == 'lesson_content_checks'
    result = {key: row[key] for key in ('id', 'job_id', 'project_id', 'conversation_id', 'artifact_id', 'title',
              'status', 'other_text', 'reply_status', 'error', 'created_at', 'updated_at')}
    result.update(source_ids=unj(row['source_ids_json'], []), difficulties=unj(row['difficulties_json'], []),
                  options=[{'id': item['id'], 'label': item['label']} for item in ([CONTENT_CHECK] if content_only else OPTIONS)],
                  content_check=requests_content_check(row),ready=bool(artifact),
                  kind='content_check' if content_only else 'understanding',
                  parent_questionnaire_id=row.get('parent_questionnaire_id'))
    if artifact: result['artifact_id'] = artifact['id']
    result['focus'] = public_focus(row)
    from .lesson_checks import latest
    result['understanding_check']=None if content_only else latest(row['id'])
    return result


def get_questionnaire(questionnaire_id: str) -> dict:
    row = one('SELECT * FROM lesson_questionnaires WHERE id=?', (questionnaire_id,))
    if not row: row = one('SELECT * FROM lesson_content_checks WHERE id=?', (questionnaire_id,))
    if not row: raise ValueError('理解问卷不存在')
    return row


def list_questionnaires(project_id: str) -> list[dict]:
    rows = many(
        'SELECT q.*,b.status AS job_status FROM lesson_questionnaires q JOIN jobs b ON b.id=q.job_id '
        'WHERE q.project_id=? ORDER BY q.created_at DESC,q.rowid DESC', (project_id,))
    rows += many('SELECT * FROM lesson_content_checks WHERE project_id=? ORDER BY created_at DESC,rowid DESC', (project_id,))
    return [public_questionnaire(row) for row in sorted(rows, key=lambda row:row['created_at'], reverse=True)]


def feedback_text(row: dict) -> str:
    labels = [BY_ID[key]['label'] for key in unj(row['difficulties_json'], [])]
    focus = saved_focus(row)
    check=requests_content_check(row)
    return (f"我对《{row['title']}》讲解的{'内容核对与理解反馈' if check else '理解反馈'}：\n" +
            ('具体位置：' + ' → '.join(focus['path']) + '\n' if focus else '') +
            (('我已在问卷中选定具体原句，请先核对所选原句。\n' if check else '我已在问卷中选定具体原句，请先围绕所选原句补讲。\n') if focus.get('selection') else '') +
            '\n'.join(f'- {label}' for label in labels) +
            (f"\n其他补充：{row['other_text']}" if row['other_text'] else '') +
            ('\n请先核对旧讲解与原资料的前提和结论；确认有误时明确更正并说明依据，成立时解释原因，不确定时说明缺少什么。我的质疑不等于旧讲解一定错，也不等于我没掌握。'
             if check else '\n请围绕这些卡点帮我补讲。'))


def source_request(row: dict) -> str:
    """Only the student's own supplement can specify source-reading scope.

    Lesson titles, selected AI headings and generated feedback labels locate
    historical teaching. They cannot authorize PDF pages or a whole-source read.
    """
    return row['other_text']


def submit_questionnaire(questionnaire_id: str, difficulties: list[str], other_text: str, skip=False, focus_section_id=None, focus_selection=None) -> dict:
    if any(key not in BY_ID for key in difficulties) or len(difficulties) != len(set(difficulties)):
        raise ValueError('请从理解困难或讲解核对选项中选择，不能重复选择')
    other_text = other_text.strip()
    if not skip and not difficulties and not other_text: raise ValueError('请选择理解困难、讲解核对或填写其他补充；也可以跳过')
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        stored = database.execute('SELECT * FROM lesson_questionnaires WHERE id=?', (questionnaire_id,)).fetchone()
        if not stored: stored = database.execute('SELECT * FROM lesson_content_checks WHERE id=?', (questionnaire_id,)).fetchone()
        if not stored: raise ValueError('理解问卷不存在')
        row = dict(stored)
        table = table_for(row)
        if table == 'lesson_content_checks' and not skip and difficulties != [CONTENT_CHECK['id']]:
            raise ValueError('此入口只核对讲解疑点；理解困难请通过原理解反馈或直接告诉导师')
        if table == 'lesson_content_checks' and not skip and not other_text and not focus_section_id:
            raise ValueError('请写下需要核对的问题，或选择讲解章节／原句，再请导师核对')
        if row['status'] != 'pending':
            if (row['status'] == 'submitted' and not skip and set(unj(row['difficulties_json'], [])) == set(difficulties) and row['other_text'] == other_text
                    and saved_focus(row).get('id') == (focus_section_id or None)
                    and selection_identity(saved_focus(row).get('selection')) == selection_identity(focus_selection)):
                return public_questionnaire(row)
            if row['status'] == 'skipped' and skip: return public_questionnaire(row)
            raise ValueError('这份问卷已经处理；后续理解变化可以直接告诉导师')
        timestamp = now()
        focus = select_focus(row, focus_section_id, database, selection=focus_selection) if not skip else {}
        row.update(status='skipped' if skip else 'submitted', difficulties_json=j(difficulties), other_text=other_text, focus_json=j(focus), updated_at=timestamp)
        database.execute(f'UPDATE {table} SET status=?,difficulties_json=?,other_text=?,focus_json=?,updated_at=? WHERE id=?',
                         (row['status'], row['difficulties_json'], other_text, row['focus_json'], timestamp, questionnaire_id))
        if not skip:
            from .learning_signals import learning_excerpt
            profile_choices=[key for key in difficulties if key != CONTENT_CHECK['id']]
            # A critique of AI content is not evidence of learner weakness.
            # Mixed feedback retains only explicitly selected learning needs;
            # the full critique stays in this questionnaire and its own chat.
            learning_text='' if requests_content_check(row) else learning_excerpt(other_text,'当前讲解的知识理解反馈。')
            # Free-form feedback remains in the questionnaire/current chat;
            # only knowledge difficulties are eligible for the global profile.
            if not profile_choices and not learning_text:return public_questionnaire(row)
            student_text = feedback_text(dict(row,difficulties_json=j(profile_choices),other_text=learning_text))
            sources = [dict(source) for sid in unj(row['source_ids_json'], []) if (source := database.execute(
                'SELECT name FROM sources WHERE id=?', (sid,)).fetchone())]
            anchors = list(dict.fromkeys([row['title'][:80]] + [Path(source['name']).stem[:60] for source in sources]))
            if focus: anchors += [title for title in knowledge_anchors(focus) if title not in anchors]
            topic = (row['title'][:40] + ' · ' + focus['title'][:25]) if focus else row['title'][:65]
            payload = {'questionnaire_id': questionnaire_id, 'source_ids': unj(row['source_ids_json'], []),
                       'topic': row['title'], 'student_text': student_text, 'difficulties': profile_choices, 'other_text': learning_text,
                       'focus': public_focus(row)}
            database.execute('INSERT INTO learning_events(event_key,project_id,conversation_id,kind,payload_json,status,created_at,updated_at) '
                             "VALUES (?,?,?,'理解问卷',?,'completed',?,?)",
                             ('questionnaire:' + questionnaire_id, row['project_id'], row['conversation_id'], j(payload), timestamp, timestamp))
            event_id = database.execute('SELECT last_insert_rowid()').fetchone()[0]
            for key in profile_choices:
                item = BY_ID[key]
                # Two concept-related choices must remain distinct despite the insight UNIQUE constraint.
                _save_insight(event_id, topic + ' · ' + item['label'][:12], 'self_report', item['dimension'],
                              ('在“' + focus['title'] + '”一节，' if focus else '') + '学生自报：' + item['label'] + '。需要进一步定位，尚未通过测验验证。',
                              item['label'], '自评（未验证）', database=database, anchors=anchors)
            if learning_text:
                _save_insight(event_id, topic[:80], 'self_report', '', '学生补充：' + learning_text[:220],
                              learning_text[:250], '自评（未验证）', database=database, anchors=anchors)
    return public_questionnaire(row)


def remediation_policy(row: dict) -> str:
    check=('''\n本次学生选择“讲解可能有误或依据不清，请先核对”。先处理内容疑点，不默认学生知识薄弱，也不默认学生的指正必定成立。
区分原资料、旧AI讲解与学生的质疑；旧AI回答和过去的“核查通过”不构成正确性证据。核对具体位置和该段实际给定的前提，不能从别段借更强条件替它补依据；本段明确仍保留更强条件时也不能忽略它。
如果旧讲解确有错误，明确指出原句的问题，给出更正和能核对的理由，再解释正确内容；如果原句成立，直接说明它依赖哪些条件、为何与学生的担忧不同。资料缺失或不能确认时保留待核实，不编造已经回查的证据。
只有内容质疑、没有明确报告理解困难时，不把质疑改写成学生不懂概念或需要补前置知识；同时选择了理解困难时，只针对这些明确选择补讲。
没有具体位置时先问一个便于定位的问题，避免无依据地重写整篇。只核对和解释，不自动出题，也不改变画像分数。\n''' if requests_content_check(row) else '')
    return focus_context(row) + check + '''\n本次是讲解后补讲。问卷是学生主观自报，不能当作客观低能力，也不直接扣分。
沿用本对话的讲解要求与学科，不机械重写整篇文章或强行跨学科；按实际反馈处理，不把所有困难都归因于前置知识缺口。
学生当前明确提出的输出形式、长度和只读懂需求优先；简单困难能直接解释时不要扩大成整堂课。
不懂术语：解释其含义、原文中的用途及必要的概念归属，不编造唯一发明者。
缺少前置知识：先说明哪一步依赖哪些前置概念，再搭建能接回当前论证的小桥。
不懂构造动机：解释目标、限制、关键观察及为什么想到该构造，区分教学重建与历史事实。
不知何时用方法：给出识别信号、适用条件及不能用的反例。
复述但不能论证：指出尚需独立建立的论证环节，示范理由如何衔接；没有学生论证时不捏造错误。
计算或实现出错：区别推理与执行，示范可检查的步骤、单位、边界或调试方法，不假定只学 Python。
只落实学生选中的困难和补充；如果没说具体术语或步骤，问一个容易回答的定位问题，并尽量先补最相关的解释。
即使原讲解附有配套习题，本次也不能擅自布置新作业、强制费曼考核或声称学生已掌握；练习须由学生另行选择。
最后用简短结构回收关键点，再询问哪一处仍不清楚；不要输出未审阅资料的断言。\n'''
