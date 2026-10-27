"""Opt-in practice scaffolds and delayed retrieval; no model calls or secret solutions in hints."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import math

from .db import connect, j, many, now, one, uid, unj
from .lesson_feedback import BY_ID


HINTS = {
    'terminology': ['圈出题干中的术语、量和限定词，先用自己的话说清各自指什么。',
                    '把容易混淆的两个概念并排比较：定义、对象、适用条件分别是什么？',
                    '将题干改写成日常语言，再换回准确术语；检查改写是否丢了条件。'],
    'prerequisites': ['写下题目希望得到什么，以及已经给了什么，标出中间缺的知识。',
                      '列出连接已知与目标可能需要的定义或结论，并逐项检查前提。',
                      '先尝试一个更简单的特例，识别它比原题少了什么困难，再接回原题。'],
    'motivation': ['先明确构造要解决的障碍：直接用已有条件为什么还到不了目标？',
                   '从目标反推需要出现的性质，再检查已知条件能提供哪些性质。',
                   '比较两个候选构造：哪个更容易满足所需性质？写出选择理由，不只记形式。'],
    'method_selection': ['列出已知条件与目标的结构，先识别问题类型，不急着套方法。',
                         '比较候选方法的触发条件、适用范围和成本，淘汰前提不满足的方法。',
                         '给所选方法找一个不能使用的反例，再检查本题是否避开这个反例。'],
    'argumentation': ['将论证分为前提、中间结论和目标，检查每个箭头依据什么。',
                       '找出最关键的一跳：它需要定义、定理、经验依据还是附加假设？',
                       '逐步写出“因为……所以……”，检查是否循环论证、偷换概念或遗漏情形。'],
    'implementation': ['先检查思路是否成立，再单独检查计算、单位、符号或实现步骤。',
                        '从第一个可独立核对的中间结果开始检查，定位最早出现差异的位置。',
                        '用简单值、极限、边界输入或另一种计算复核；区分方法错误和执行错误。'],
    'unknown': ['先写出已知、目标和目前做到的步骤，标出第一次不确定的位置。',
                '判断卡点更像术语、前置、构造动机、方法选择、论证还是计算实现。',
                '尝试一个简单特例并说明哪里能做、哪里不能做；提交后据实际作答定位原因。'],
}


def clock_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    value = datetime.fromisoformat(value)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def questions_for(set_id):
    row = one('SELECT * FROM exercise_sets WHERE id=?', (set_id,))
    if not row: raise ValueError('习题不存在')
    questions = unj(row['questions_json'], [])
    if not questions or any(q.get('language') for q in questions):
        raise ValueError('本项提示与混合复习用于普通习题；编程作业保留现有提交与审查方式')
    return row, questions


def completed_submission(set_id, questions, database=None):
    sql = 'SELECT * FROM submissions WHERE exercise_set_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1'
    row = database.execute(sql, (set_id,)).fetchone() if database else one(sql, (set_id,))
    if not row: return None
    row = dict(row)
    answers = unj(row['answers_json'], [])
    return row if len(answers) == len(questions) and all(isinstance(a, str) and a.strip() for a in answers) else None


def policy(set_id):
    row = one('SELECT recovery_mode FROM practice_options WHERE exercise_set_id=?', (set_id,))
    return row['recovery_mode'] if row else 'strict'


def public_practice(set_id):
    hints = many('SELECT question_index,kind,MAX(level) AS level FROM practice_hints WHERE exercise_set_id=? '
                 'GROUP BY question_index,kind', (set_id,))
    session = one('SELECT items_json,started_at FROM review_sessions WHERE exercise_set_id=?', (set_id,))
    return {'recovery_mode': policy(set_id), 'hint_usage': hints, 'is_review': bool(session),
            'review_started_at': session['started_at'] if session else None,
            'version_notice':('本题单使用保存的原题与评分版本；源题更新不会自动替换。'
                +('含旧版本未核实记录，不作为已验证的同题延迟证据。' if any(entry.get('same_question_verified') is not True for entry in unj(session['items_json'],[])) else '')
                if session else '')}


def get_hint(set_id, index, kind, level):
    row, questions = questions_for(set_id)
    if row['status'] != 'assigned': raise ValueError('已提交后请查看解析；思考提示只在提交前使用')
    if kind not in HINTS or type(level) is not int or not 1 <= level <= 3:
        raise ValueError('请选择有效卡点和1到3层提示')
    if type(index) is not int or index < 0 or index >= len(questions): raise ValueError('题号不存在')
    # A fixed directional scaffold cannot copy a private answer, even if the
    # problem/student input contains instructions. This is not an AI solution.
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        current = database.execute('SELECT status FROM exercise_sets WHERE id=?', (set_id,)).fetchone()
        if not current or current['status'] != 'assigned':
            raise ValueError('已提交后请查看解析；思考提示只在提交前使用')
        if database.execute('SELECT 1 FROM homework_attempts WHERE exercise_set_id=? LIMIT 1',(set_id,)).fetchone():
            raise ValueError('本题单已有完整提交，请查看已交付解析或等待批改；不会把提交后的提示计入本次作答')
        if database.execute('SELECT 1 FROM practice_submission_locks WHERE exercise_set_id=? AND expires_at>?',
                            (set_id, clock_now().isoformat())).fetchone():
            raise ValueError('正在批改本次作答，请等待结束后查看解析')
        if database.execute("SELECT 1 FROM jobs WHERE json_extract(payload_json,'$.set_id')=? "
                            "AND kind='quiz_grade' AND status IN ('queued','running','pausing','paused')",
                            (set_id,)).fetchone():
            raise ValueError('本次作答已进入批改任务，请先继续或取消该任务')
        database.execute('INSERT OR IGNORE INTO practice_hints VALUES (?,?,?,?,?)', (set_id, index, kind, level, now()))
    return {'question_index': index, 'kind': kind, 'level': level, 'hint': HINTS[kind][level - 1],
            'notice': '思考方向提示，不是针对本题的完整解析；使用层数会保留，不能据此声称独立完成。'}


@contextmanager
def submission_guard(set_id):
    from .workflows import current_control
    control=current_control.get()
    token = (control.job_id+':' if control else '')+uid()
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        if not database.execute('SELECT 1 FROM exercise_sets WHERE id=?', (set_id,)).fetchone(): raise ValueError('习题不存在')
        if database.execute("SELECT 1 FROM jobs WHERE json_extract(payload_json,'$.set_id')=? "
                            "AND json_extract(payload_json,'$.workflow_version')=1 "
                            "AND status IN ('queued','running','pausing','paused') AND id<>?",
                            (set_id,control.job_id if control else '')).fetchone():
            raise ValueError('本套习题已有进行中或暂停的任务，请先完成或取消')
        database.execute('DELETE FROM practice_submission_locks WHERE exercise_set_id=? AND expires_at<=?',
                         (set_id, clock_now().isoformat()))
        if database.execute('SELECT 1 FROM practice_submission_locks WHERE exercise_set_id=?', (set_id,)).fetchone():
            raise ValueError('本套习题正在批改，请等待完成后再提交')
        database.execute('INSERT INTO practice_submission_locks VALUES (?,?,?)',
                         (set_id, token, (clock_now() + timedelta(minutes=15)).isoformat()))
    try: yield
    finally:
        with connect() as database:
            database.execute('DELETE FROM practice_submission_locks WHERE exercise_set_id=? AND token=?', (set_id, token))


def attempt_context(set_id, used_notes=None):
    hints = many('SELECT question_index,MAX(level) AS level FROM practice_hints WHERE exercise_set_id=? GROUP BY question_index', (set_id,))
    session = one('SELECT * FROM review_sessions WHERE exercise_set_id=?', (set_id,))
    timing = []
    for item in unj(session['items_json'], []) if session else []:
        timing.append({'question_index': item['review_index'], 'delay_hours': round(max(0, (parse_time(session['started_at']) -
            parse_time(item['baseline_at'])).total_seconds() / 3600), 2),
            'due_reached': parse_time(session['started_at']) >= parse_time(item['due_at']),
            'same_question_verified':item.get('same_question_verified') is True})
    return {'hint_levels': {str(x['question_index']): x['level'] for x in hints}, 'used_notes': used_notes,
            'is_review': bool(session), 'timing': timing,
            'notice': '间隔从上次完成作答到本次打开复习计算，不证明期间未再接触材料。提示记录只涵盖本软件；是否看笔记是学生自报，不证明未获其他帮助。'}


def diagnostics(grade, questions, answers):
    proposed = grade.get('diagnostics', [])
    output = []
    for index, question in enumerate(questions):
        if isinstance(grade.get('scores'),list) and index<len(grade['scores']) and grade['scores'][index] is not None and grade['scores'][index]>=100:
            continue  # Full credit is not a reason to invent a missing error cause.
        entry = next((x for x in proposed if isinstance(x, dict) and type(x.get('index')) is int and x['index'] == index), {}) if isinstance(proposed, list) else {}
        kind, quote = entry.get('kind'), entry.get('quote')
        verified = isinstance(kind, str) and kind in BY_ID and isinstance(quote, str) and 2 <= len(quote) <= 250 and quote in answers[index]
        reason = entry.get('reason')
        output.append({'index': index, 'topic': question['topic'], 'kind': kind if verified else 'unknown',
                       'label': BY_ID[kind]['label'] if verified else '原因待定位',
                       'quote': quote if verified else '', 'reason': reason[:400] if verified and isinstance(reason, str) else
                       '现有批改未提供可核对的原因证据；不能仅凭低分判断缺少哪种能力。',
                       'status': '暂定诊断' if verified else '待定位',
                       'next_step': HINTS[kind if verified else 'unknown'][0]})
    return output


def finite_scores(values, count):
    if not isinstance(values, list) or len(values) != count: raise RuntimeError('批改未返回完整逐题分数')
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in values): raise RuntimeError('批改分数无效，未保存成绩')
    if any(not 0 <= x <= 100 for x in values): raise RuntimeError('批改分数不在 0 到 100 之间，未保存成绩')
    return [float(x) for x in values]


def _require_review_project(project_id,database):
    if not database.execute('SELECT 1 FROM projects p WHERE p.id=? AND NOT EXISTS '
            '(SELECT 1 FROM removed_projects x WHERE x.project_id=p.id)',(project_id,)).fetchone():
        raise ValueError('复习相关项目不存在或已移入回收站，请先恢复项目再继续；原安排保留')


def schedule_review(set_id, interval_days=1, indices=None):
    row, questions = questions_for(set_id)
    submission = completed_submission(set_id, questions)
    if not submission: raise ValueError('请先完整提交并批改本套习题，再加入复习')
    if unj(submission['grade_json'],{}).get('grading_verification_required'):raise ValueError('评分尚待核实，请先重新复核后再加入复习')
    if type(interval_days) is not int or not 1 <= interval_days <= 90: raise ValueError('复习间隔为1到90天')
    indices = list(range(len(questions))) if indices is None else indices
    if not indices or len(indices) != len(set(indices)) or any(type(i) is not int or i < 0 or i >= len(questions) for i in indices):
        raise ValueError('请选择有效且不重复的题号')
    timestamp = clock_now().isoformat()
    due = (clock_now() + timedelta(days=interval_days)).isoformat()
    session = one('SELECT items_json FROM review_sessions WHERE exercise_set_id=?', (set_id,))
    mapped = {x['review_index']: x for x in unj(session['items_json'], [])} if session else {}
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        _require_review_project(row['project_id'],database)
        from . import review_versions as versions
        current=database.execute('SELECT * FROM exercise_sets WHERE id=?',(set_id,)).fetchone()
        if not current or versions.assessment_basis(dict(current))['worksheet_sha256']!=versions.assessment_basis(row)['worksheet_sha256']:
            raise ValueError('安排期间题目版本已变更，请刷新后重试')
        checked=set()
        for index in indices:
            origin_set = mapped[index]['origin_set_id'] if index in mapped else set_id
            origin_index = mapped[index]['question_index'] if index in mapped else index
            if origin_set not in checked:
                origin=database.execute('SELECT project_id FROM exercise_sets WHERE id=?',(origin_set,)).fetchone()
                if not origin:raise ValueError('复习原题已不存在，请重新选择题目')
                _require_review_project(origin['project_id'],database);checked.add(origin_set)
            old = database.execute('SELECT * FROM review_items WHERE origin_set_id=? AND question_index=?', (origin_set, origin_index)).fetchone()
            if old and old['active_set_id']: raise ValueError('该题正在复习，完成当前作答后再调整间隔')
            snapshot=versions.material(row,index)
            verified=versions.assessed_question(row,submission,index,database)
            if index in mapped:
                verified=verified and mapped[index].get('same_question_verified') is True
                expected=mapped[index].get('origin_version_sha256')
                if expected and expected!=versions.question_fingerprint(snapshot):
                    raise ValueError('复习题目版本与原安排不一致，请核对原题单')
                bound=versions.load(database,old['id']) if old else None
                if bound:
                    if versions.question_fingerprint(bound['material'])!=versions.question_fingerprint(snapshot):
                        raise ValueError('原安排已是其他题目版本，请先核对复习范围')
                    snapshot=bound['material']
                else:snapshot['difficulty']=mapped[index].get('origin_difficulty',snapshot['difficulty'])
            # Changing the plan is not another retrieval attempt. Preserve the
            # last completed practice time when queuing or rescheduling past sets.
            baseline = max(parse_time(submission['created_at']), parse_time(old['baseline_at'])) if old else parse_time(submission['created_at'])
            database.execute('INSERT INTO review_items VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(origin_set_id,question_index) '
                             'DO UPDATE SET interval_days=excluded.interval_days,baseline_at=excluded.baseline_at,due_at=excluded.due_at,updated_at=excluded.updated_at',
                             (uid(), origin_set, origin_index, interval_days, baseline.isoformat(), due, None, timestamp, timestamp))
            saved=database.execute('SELECT id FROM review_items WHERE origin_set_id=? AND question_index=?',(origin_set,origin_index)).fetchone()
            versions.save(database,saved['id'],snapshot,verified)
    return {'scheduled': len(indices), 'due_at': due, 'interval_days': interval_days}


def review_queue(offset=0, limit=50, due_only=False, selected_ids=None):
    if selected_ids is not None and (not isinstance(selected_ids,list) or len(selected_ids)>6
            or any(not isinstance(value,str) or not value for value in selected_ids)):
        raise ValueError('一次只核对最多6个已选复习项')
    stamp=clock_now()
    source=('FROM review_items r JOIN exercise_sets e ON e.id=r.origin_set_id JOIN projects p ON p.id=e.project_id '
        'WHERE NOT EXISTS (SELECT 1 FROM removed_projects x WHERE x.project_id=p.id) '
        'AND (r.active_set_id IS NULL OR EXISTS (SELECT 1 FROM exercise_sets a JOIN projects ap ON ap.id=a.project_id '
        'WHERE a.id=r.active_set_id AND NOT EXISTS (SELECT 1 FROM removed_projects x WHERE x.project_id=ap.id)))')
    condition = ' AND (r.due_at<=? OR r.active_set_id IS NOT NULL)' if due_only else ''
    args = (stamp.isoformat(),) if due_only else ()
    sql = 'SELECT r.*,e.title,e.project_id,e.questions_json,p.name AS project_name '+source+condition
    rows = many(sql + ' ORDER BY r.due_at,r.id LIMIT ? OFFSET ?', args + (limit, offset))
    for row in rows:
        questions = unj(row.pop('questions_json'), [])
        q = questions[row['question_index']] if row['question_index'] < len(questions) else {}
        row['topic'] = q.get('topic', '题目已变化')
        row['due'] = parse_time(row['due_at']) <= stamp
    from .review_versions import annotate
    annotate(rows)
    result={'items': rows, 'total': one('SELECT COUNT(*) AS n FROM (' + sql + ')', args)['n'], 'offset': offset, 'limit': limit,
            'due_count': one('SELECT COUNT(*) AS n '+source+' AND r.due_at<=?',(stamp.isoformat(),))['n']}
    if selected_ids is not None:
        eligible={item['id'] for item in many('SELECT r.id '+source+' AND r.active_set_id IS NULL AND r.id IN ('+
            ','.join('?' for _ in selected_ids)+')',tuple(selected_ids))} if selected_ids else set()
        result['selected_ids']=[value for value in selected_ids if value in eligible]
    return result


def remove_review(item_id):
    with connect() as database:
        if not database.execute('SELECT 1 FROM review_items WHERE id=?', (item_id,)).fetchone(): raise ValueError('复习记录不存在')
        database.execute('DELETE FROM review_items WHERE id=?', (item_id,))
    return {'removed': True}


def start_review(project_id, item_ids):
    if not 1 <= len(item_ids) <= 6 or len(item_ids) != len(set(item_ids)): raise ValueError('一次选择1到6道不同的复习题')
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        _require_review_project(project_id,database)
        items = []
        for item_id in item_ids:
            row = database.execute('SELECT * FROM review_items WHERE id=?', (item_id,)).fetchone()
            if not row: raise ValueError('复习记录已移除，请刷新队列')
            origin=database.execute('SELECT project_id FROM exercise_sets WHERE id=?',(row['origin_set_id'],)).fetchone()
            if not origin:raise ValueError('复习原题已不存在，请刷新队列')
            _require_review_project(origin['project_id'],database)
            items.append(dict(row))
        active = {x['active_set_id'] for x in items if x['active_set_id']}
        if active:
            if len(active) == 1 and all(x['active_set_id'] in active for x in items):
                existing = database.execute('SELECT project_id FROM exercise_sets WHERE id=?', (next(iter(active)),)).fetchone()
                if not existing:raise ValueError('原复习题单已不存在，请移出原安排后重新选择')
                _require_review_project(existing['project_id'],database)
                session=database.execute('SELECT items_json FROM review_sessions WHERE exercise_set_id=?',(next(iter(active)),)).fetchone()
                original=unj(session['items_json'],[]) if session else []
                if {item.get('id') for item in original}!=set(item_ids):
                    raise ValueError('所选范围与原复习题单不同，请用“继续作答”打开完整原复习，或移出安排后重新选择')
                if existing['project_id'] == project_id:
                    from .review_versions import resolve
                    for item in items:resolve(database,item)
                    return next(iter(active)), True
            raise ValueError('部分题目已有进行中的复习，请先打开原练习完成或重新选择')
        public, private, origins = [], [], []
        from .review_versions import resolve,question_fingerprint
        difficulties=[]
        for index, item in enumerate(items):
            bound=resolve(database,item);snapshot=bound['material']
            public.append(dict(snapshot['question'],index=index))
            private.append(dict(snapshot['solution'],index=index))
            difficulties.append(snapshot['difficulty'])
            origins.append(dict(item, review_index=index,origin_version_sha256=question_fingerprint(snapshot),
                origin_difficulty=snapshot['difficulty'],same_question_verified=bound['verified']))
        set_id, timestamp = uid(), clock_now().isoformat()
        difficulty = max(1, min(5, round(sum(difficulties)/len(difficulties))))
        local_date = parse_time(timestamp).astimezone().strftime('%Y-%m-%d')
        database.execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
                         (set_id, project_id, '[]', '混合复习 · ' + local_date, j(public), j(private), difficulty, 'assigned', timestamp))
        database.execute('INSERT INTO practice_options VALUES (?,?,?)', (set_id, 'adaptive', timestamp))
        database.execute('INSERT INTO review_sessions VALUES (?,?,?,NULL)', (set_id, j(origins), timestamp))
        database.executemany('UPDATE review_items SET active_set_id=?,updated_at=? WHERE id=?', [(set_id, timestamp, x['id']) for x in items])
    return set_id, False


def finish_review(set_id):
    row = one('SELECT * FROM review_sessions WHERE exercise_set_id=?', (set_id,))
    if not row or row['completed_at']: return
    timestamp = clock_now()
    with connect() as database:
        database.execute('UPDATE review_sessions SET completed_at=? WHERE exercise_set_id=?', (timestamp.isoformat(), set_id))
        for item in unj(row['items_json'], []):
            from . import review_versions as versions
            active=database.execute('SELECT * FROM review_items WHERE id=? AND active_set_id=?',(item['id'],set_id)).fetchone()
            if not active:continue
            worksheet=database.execute('SELECT * FROM exercise_sets WHERE id=?',(set_id,)).fetchone()
            snapshot=versions.material(dict(worksheet),item['review_index'])
            bound=versions.load(database,item['id']) or versions.save(database,item['id'],snapshot,False)
            content=versions.question_fingerprint(snapshot)
            if versions.question_fingerprint(bound['material'])!=content or (item.get('origin_version_sha256') and item['origin_version_sha256']!=content):
                raise ValueError('完成的复习版本与原安排不符，不能重置其他版本的复习间隔')
            submission=completed_submission(set_id,unj(worksheet['questions_json'],[]),database)
            basis=unj(submission['grade_json'],{}).get('assessment_version',{}) if submission else {}
            if isinstance(basis,dict) and basis.get('original_verified') is True and item['review_index']<len(basis.get('question_sha256',[])) and basis['question_sha256'][item['review_index']]==content:
                # This completed attempt establishes a new known baseline; its
                # already recorded old/unknown starting interval is unchanged.
                database.execute('UPDATE review_item_versions SET verified=1 WHERE review_item_id=?',(item['id'],))
            database.execute('UPDATE review_items SET baseline_at=?,due_at=?,active_set_id=NULL,updated_at=? WHERE id=? AND active_set_id=?',
                             (timestamp.isoformat(), (timestamp + timedelta(days=item['interval_days'])).isoformat(), timestamp.isoformat(), item['id'], set_id))
