import asyncio
import pytest
from fastapi.testclient import TestClient

from studyforge import learning_memory as memory, learning_profile as profile, server
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, update_mastery


def assessment(key, score=60, topic='高斯定律'):
    update_mastery(topic, quiz=score)
    memory.assessment_record(key, topic, '做题', score, '真实作答', '实测评分')


def rate(score, topic='高斯定律'):
    response = TestClient(server.app).post('/api/profile/rating', json={'topic':topic, 'rating':score, 'difficulty_rating':80})
    assert response.status_code == 200, response.text
    return response.json()


def test_self_score_influences_composite_teacher_and_saved_generation_context():
    assessment('quiz')
    row = rate(100)
    assert row['score'] == row['assessment_score'] == 60
    assert row['learning_score'] == 68 and row['self_rating_gap'] == 40
    assert row['learning_score_basis'] == 'assessment_and_self_report'
    text = memory.profile_context('高斯定律')
    assert '综合学习参考分 68/100' in text and '自评 20%' in text
    project = create_project('讲解')
    job = create_job(project['id'], 'generate', {})
    assert profile.generation_profile(job)[0]['learning_score'] == 68
    client = TestClient(server.app)
    assert client.put('/api/profile/scoring', json={'self_report_weight':40}).json()['assessment_weight'] == 60
    assert profile.generation_profile(job)[0]['learning_score'] == 76
    assert profile.mentor_profile('高斯定律')['topics'][0]['learning_score'] == 76
    assert '综合学习参考分 76/100' in memory.profile_context('高斯定律')
    assert one('SELECT * FROM mastery')['score'] == 60  # Exam/80-point gates use their real grades.
    assert TestClient(server.app).get('/api/profile/scoring').json()['self_report_weight'] == 40


def test_latest_self_rating_does_not_accumulate_weight_and_unknown_scores_are_not_zero():
    assessment('quiz')
    rate(100); row = rate(20)
    assert row['learning_score'] == 52 and row['self_rating'] == 20
    assert row['self_report_count'] == 2
    row = rate(90, '未做过题的知识')
    assert row['score'] is None and row['learning_score'] == 90
    assert row['learning_score_basis'] == 'self_report_only' and row['assessment_count'] == 0
    assert '只有学生自评，未测验' in memory.profile_context('未做过题的知识')
    assessment('other', 50, '没有自评')
    row = next(row for row in profile.effective_profile() if row['topic'] == '没有自评')
    assert row['learning_score'] == 50 and row['learning_score_basis'] == 'assessment_only'


def test_self_evidence_removal_and_restore_recomputes_composite_without_changing_quiz():
    assessment('quiz'); rate(100)
    insight = one('SELECT id FROM learning_insights ORDER BY id DESC LIMIT 1')
    result = profile.change_insight(insight['id'], 0, deleted=True)
    assert profile.effective_profile()[0]['learning_score'] == 60
    profile.change_insight(insight['id'], result['version'], deleted=False)
    assert profile.effective_profile()[0]['learning_score'] == 68


@pytest.mark.parametrize('weight', [-1, 51, 20.5, True, None, '20'])
def test_scoring_weight_rejects_invalid_values(weight):
    client = TestClient(server.app)
    assert client.put('/api/profile/scoring', json={'self_report_weight':weight}).status_code == 400
    assert client.get('/api/profile/scoring').json()['self_report_weight'] == 20


def test_zero_weight_returns_assessment_without_changing_self_report_record():
    assessment('quiz'); rate(100)
    profile.save_scoring_settings({'self_report_weight':0})
    row = profile.effective_profile()[0]
    assert row['learning_score'] == row['score'] == 60 and row['self_rating'] == 100
    assert row['learning_score_basis'] == 'assessment_only'
    assert len(many('SELECT * FROM learning_events')) == 2


@pytest.mark.parametrize('score,requires_feynman', [(79, True), (80, False)])
def test_composite_above_eighty_cannot_override_real_grade_and_feynman_gate(score, requires_feynman):
    from studyforge.exercises import grade_submission
    assessment('quiz'); rate(100)
    profile.save_scoring_settings({'self_report_weight':50})
    assert profile.effective_profile()[0]['learning_score'] == 80
    project, worksheet = create_project('真实评分边界'), uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)', (worksheet, project['id'], '[]', '高斯定律',
        j([{'index':0,'question':'解释高斯定律的适用条件','topic':'高斯定律'}]),
        j([{'index':0,'solution':'正确解答','rubric':'核查概念与论证'}]), 1, 'assigned', now()))
    class Grader:
        model = 'test-model'
        async def complete(self, *args, **kwargs): return j({'scores':[score], 'feedback':['按本次答案给分'], 'uncertainties':[]})
    grade = asyncio.run(grade_submission(Grader(), worksheet, ['我的答案'], recovery_mode='strict', used_notes=False))
    assert grade['score'] == score and grade['requires_feynman'] is requires_feynman
    assert one('SELECT score FROM submissions WHERE exercise_set_id=?', (worksheet,))['score'] == score
