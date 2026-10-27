"""Private, immutable review material; fingerprints describe identity, not truth."""
import copy
import hashlib
import json

from .db import j,many,now,one,unj


class ReviewVersionConflict(ValueError):
    """A model retry cannot repair changed or missing assessment provenance."""


def require_unchanged(worksheet, database=None):
    """Fence async teaching results against their exact original worksheet.

    Status and title may change normally. The question, reference (including
    executable tests), difficulty and owning project must still match. Call
    with the write transaction when committing a grade.
    """
    query='SELECT * FROM exercise_sets WHERE id=? AND project_id=?'
    params=(worksheet['id'],worksheet['project_id'])
    current=database.execute(query,params).fetchone() if database is not None else one(query,params)
    if not current or any(current[key]!=worksheet[key] for key in ('questions_json','solutions_json','difficulty')):
        raise ReviewVersionConflict('任务期间题目、参考解或评分标准已变更，已停止保存和交付本阶段结果；请核对原题版本')
    return dict(current)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def valid_material(value):
    return (isinstance(value,dict) and set(value)=={'question','solution','difficulty'}
        and isinstance(value['question'],dict) and isinstance(value['question'].get('question'),str)
        and isinstance(value['question'].get('topic'),str) and isinstance(value['solution'],dict)
        and isinstance(value['solution'].get('solution'),str) and 'rubric' in value['solution']
        and type(value['difficulty']) is int and 1<=value['difficulty']<=5)


def material(worksheet,index):
    questions=unj(worksheet['questions_json'],[]);solutions=unj(worksheet['solutions_json'],[])
    if type(index) is not int or not 0<=index<len(questions):raise ValueError('原题版本中没有这个题号')
    question=questions[index]
    matches=[item for item in solutions if item.get('index')==question.get('index')]
    if len(matches)!=1 or question.get('language'):raise ValueError('原题版本的普通习题或评分依据不完整')
    solution=matches[0]
    if not isinstance(question.get('question'),str) or not isinstance(question.get('topic'),str) or not isinstance(solution.get('solution'),str) or 'rubric' not in solution:
        raise ValueError('原题版本缺少题干、解析或评分标准')
    return {'question':{key:copy.deepcopy(value) for key,value in question.items() if key!='index'},
        'solution':{key:copy.deepcopy(solution[key]) for key in ('solution','rubric')},'difficulty':worksheet['difficulty']}


def question_fingerprint(snapshot):
    # A mixed worksheet has one aggregate reference difficulty. That must not
    # make its unchanged individual questions look like different questions.
    return fingerprint({key:snapshot[key] for key in ('question','solution')})


def assessment_basis(worksheet,original_verified=True):
    snapshots=[material(worksheet,index) for index in range(len(unj(worksheet['questions_json'],[])))]
    return {'version':1,'worksheet_sha256':fingerprint(snapshots),
        'question_sha256':[question_fingerprint(snapshot) for snapshot in snapshots],'original_verified':original_verified}


def require_assessed_version(worksheet,submission):
    """Check a dependent teaching baseline; unknown legacy evidence stays unknown."""
    grade=unj(submission['grade_json'],{});basis=grade.get('assessment_version')
    expected=None;verified=False
    if isinstance(basis,dict) and basis.get('version')==1:
        expected=basis.get('worksheet_sha256');verified=basis.get('original_verified') is True
        if not isinstance(expected,str) or len(expected)!=64:
            raise ReviewVersionConflict('原评分的题目版本记录不完整，请核对原作答；不会混用当前题目')
    else:
        attempt=one('SELECT source_version,grade_json FROM homework_attempts WHERE exercise_set_id=? '
            'AND project_id=? AND answers_json=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
            (worksheet['id'],worksheet['project_id'],submission['answers_json']))
        if attempt and unj(attempt['grade_json'],{}).get('submission_id')==submission['id']:
            saved=unj(attempt['source_version'],[])
            if isinstance(saved,list) and len(saved)==3:
                try:expected=assessment_basis({'questions_json':saved[0],'solutions_json':saved[1],'difficulty':saved[2]})['worksheet_sha256']
                except (ValueError,TypeError,KeyError):pass
                else:verified=True
    if expected is not None and expected!=assessment_basis(worksheet)['worksheet_sha256']:
        raise ReviewVersionConflict('题目或评分标准版本已变更，不能把旧成绩与当前新题混用；请查看原批改或完成当前版本后再练')
    return verified


def validate_review(worksheet):
    session=one('SELECT items_json FROM review_sessions WHERE exercise_set_id=?',(worksheet['id'],))
    for entry in unj(session['items_json'],[]) if session else []:
        expected=entry.get('origin_version_sha256')
        if expected and question_fingerprint(material(worksheet,entry['review_index']))!=expected:
            raise ReviewVersionConflict('复习题目或评分版本已变更，不能把新题作为原题复习提交；请重新选择题单')


def assessed_question(worksheet,submission,index,database):
    grade=unj(submission['grade_json'],{});basis=grade.get('assessment_version')
    expected=None;verified=False
    if isinstance(basis,dict) and basis.get('version')==1 and isinstance(basis.get('question_sha256'),list):
        if index>=len(basis['question_sha256']):raise ReviewVersionConflict('题目版本已更新，请完成当前版本后重新安排；已有原版复习保留')
        expected=basis['question_sha256'][index];verified=basis.get('original_verified') is True
    else:
        # Older detailed submissions already retained the complete accepted
        # source version. Use only a matching submission and student answers.
        attempt=database.execute('SELECT source_version,grade_json FROM homework_attempts WHERE exercise_set_id=? '
            'AND project_id=? AND answers_json=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
            (worksheet['id'],worksheet['project_id'],submission['answers_json'])).fetchone()
        if attempt and unj(attempt['grade_json'],{}).get('submission_id')==submission['id']:
            saved=unj(attempt['source_version'],[])
            if isinstance(saved,list) and len(saved)==3:
                old={'questions_json':saved[0],'solutions_json':saved[1],'difficulty':saved[2]}
                expected=question_fingerprint(material(old,index));verified=True
    if expected is not None and expected!=question_fingerprint(material(worksheet,index)):
        raise ReviewVersionConflict('题目或评分标准已变更，请完成当前版本后再加入复习；已保存的原版复习仍保留')
    return verified


def load(database,item_id):
    row=database.execute('SELECT * FROM review_item_versions WHERE review_item_id=?',(item_id,)).fetchone()
    if not row:return None
    snapshot=unj(row['snapshot_json'],None)
    if not valid_material(snapshot) or fingerprint(snapshot)!=row['fingerprint']:
        raise ReviewVersionConflict('复习版本记录不完整，请移出该安排后重新加入；不会改用其他题目')
    return {'material':snapshot,'fingerprint':row['fingerprint'],'verified':bool(row['verified'])}


def save(database,item_id,snapshot,verified):
    old=load(database,item_id);digest=fingerprint(snapshot)
    if old:
        if old['fingerprint']!=digest:raise ReviewVersionConflict('已有不同版本的复习安排，请先移出原安排再加入当前版本')
        return old  # A later score cannot retroactively verify an old baseline.
    database.execute('INSERT INTO review_item_versions VALUES (?,?,?,?,?)',(item_id,j(snapshot),digest,int(verified),now()))
    return {'material':snapshot,'fingerprint':digest,'verified':bool(verified)}


def resolve(database,item):
    old=load(database,item['id'])
    if old:return old
    if item['active_set_id']:
        session=database.execute('SELECT items_json FROM review_sessions WHERE exercise_set_id=?',(item['active_set_id'],)).fetchone()
        mapped=[entry for entry in unj(session['items_json'],[]) if entry.get('id')==item['id']] if session else []
        worksheet=database.execute('SELECT * FROM exercise_sets WHERE id=?',(item['active_set_id'],)).fetchone()
        if len(mapped)!=1 or not worksheet:raise ValueError('旧复习版本无法核实，请先查看原复习记录')
        return save(database,item['id'],material(dict(worksheet),mapped[0]['review_index']),False)
    worksheet=database.execute('SELECT * FROM exercise_sets WHERE id=?',(item['origin_set_id'],)).fetchone()
    if not worksheet:raise ValueError('复习原题已不存在')
    worksheet=dict(worksheet)
    from .practice import completed_submission
    submission=completed_submission(worksheet['id'],unj(worksheet['questions_json'],[]),database)
    if not submission or unj(submission['grade_json'],{}).get('grading_verification_required'):
        raise ValueError('原题尚未完成可靠评分，不能安排复习')
    proof=assessed_question(worksheet,submission,item['question_index'],database)
    return save(database,item['id'],material(worksheet,item['question_index']),proof)


def annotate(rows):
    """Bounded batch reads; no private snapshot enters the queue response."""
    if not rows:return
    marks=','.join('?' for _ in rows)
    bindings={row['review_item_id']:row for row in many('SELECT * FROM review_item_versions WHERE review_item_id IN ('+marks+')',tuple(row['id'] for row in rows))}
    ids=list({row['origin_set_id'] for row in rows})
    sources={row['id']:row for row in many('SELECT * FROM exercise_sets WHERE id IN ('+','.join('?' for _ in ids)+')',tuple(ids))}
    for row in rows:
        binding=bindings.get(row['id']);row.update(source_changed=False,version_verified=False)
        if not binding:
            row['version_notice']='旧安排未保存原题版本，需按可用题面练习；不作已核实的同题延迟证据'
            continue
        snapshot=unj(binding['snapshot_json'],{})
        if not valid_material(snapshot) or fingerprint(snapshot)!=binding['fingerprint']:
            row['version_notice']='复习版本记录不完整，需移出后重新加入';continue
        row['topic']=snapshot['question']['topic'];row['version_verified']=bool(binding['verified'])
        try:row['source_changed']=fingerprint(material(sources[row['origin_set_id']],row['question_index']))!=binding['fingerprint']
        except (ValueError,KeyError):row['source_changed']=True
        row['version_notice']=('原题已更新，本次仍用加入复习时保存的版本。' if row['source_changed'] else '使用加入复习时保存的原题与评分版本。')
        if not row['version_verified']:row['version_notice']+='旧作答版本未核实，不作为已验证的同题延迟证据。'
