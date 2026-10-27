from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/homework-inflight-final-20261026'
gate.FILES=['studyforge/homework.py','studyforge/coding.py','studyforge/review_versions.py',
    'web/help/guide.html','web/mobile/sw.js']
gate.TESTS=['homework_inflight','homework_versions','homework','homework_reader','homework_context',
    'homework_analysis_reuse','homework_recovery_policy','coding','coding_runtime','review_versions',
    'assessment_quality','practice','repair_learning','dialogue_profile_scope','mobile_access',
    'task_retry','task_exercise_workflows','teaching_review','user_guide']

if __name__=='__main__':gate.main()
