"""Bind an already committed assessment to its exact detailed submission.

The binding, grade, and learning evidence share the grader's transaction.
Recovery never searches for a convenient latest score or updates mastery.
"""
from .db import connect,j,now,unj
from .review_versions import ReviewVersionConflict


def save(database,attempt_id,worksheet,answers,grade):
    if not attempt_id:return
    from .homework import version
    row=database.execute('SELECT * FROM homework_attempts WHERE id=? AND exercise_set_id=? AND project_id=?',
        (attempt_id,worksheet['id'],worksheet['project_id'])).fetchone()
    if (not row or row['source_version']!=version(worksheet) or unj(row['answers_json'])!=answers or
        grade.get('homework_attempt_id')!=attempt_id or not grade.get('submission_id')):
        raise ReviewVersionConflict('评分与原提交无法对应，未保存本次成绩；请核对作答记录')
    database.execute("UPDATE homework_attempts SET grade_json=?,status='grading',updated_at=? WHERE id=?",
        (j(grade),now(),attempt_id))


def restore(attempt_id,worksheet):
    from .homework import version
    with connect() as database:
        database.execute('BEGIN')
        row=database.execute('SELECT * FROM homework_attempts WHERE id=? AND exercise_set_id=? AND project_id=?',
            (attempt_id,worksheet['id'],worksheet['project_id'])).fetchone()
        if not row:raise ReviewVersionConflict('原提交已不存在，不能恢复评分')
        try:grade=unj(row['grade_json'],{})
        except (ValueError,TypeError) as exc:
            raise ReviewVersionConflict('原评分记录无法解析，不能猜测恢复或重复评分') from exc
        if isinstance(grade,dict) and not grade:return None
        if (not isinstance(grade,dict) or not {'score','submission_id','homework_attempt_id'}<=set(grade) or
            grade.get('homework_attempt_id')!=attempt_id):
            raise ReviewVersionConflict('原评分缺少可核实的提交关联，不能猜测恢复或重复评分')
        saved=database.execute('SELECT * FROM submissions WHERE id=? AND exercise_set_id=?',
            (grade.get('submission_id'),worksheet['id'])).fetchone()
        try:
            answers=unj(row['answers_json'],[])
            coding=any(q.get('language') for q in unj(worksheet['questions_json'],[]))
            committed=unj(saved['grade_json'],{}) if saved else {}
            saved_answers=unj(saved['answers_json']) if saved else None
        except (ValueError,TypeError,AttributeError) as exc:
            raise ReviewVersionConflict('原题、作答或成绩记录无法解析，不能恢复评分') from exc
        expected={'code':answers[0]} if coding and len(answers)==1 else answers
        if (row['source_version']!=version(worksheet) or not saved or saved_answers!=expected or
            not isinstance(committed,dict) or any(key not in committed or committed[key]!=value for key,value in grade.items()) or
            set(committed)-set(grade)-{'error_analysis','feedback_artifact'} or
            saved['score']!=(grade['score'] if grade.get('score') is not None else -1)):
            raise ReviewVersionConflict('已保存评分与原题、作答或成绩记录不一致，不能恢复；请核对原记录')
        return grade
