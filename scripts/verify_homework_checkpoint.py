from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/homework-checkpoint-final-20261026'
gate.FILES=['studyforge/homework_checkpoint.py','studyforge/homework.py','studyforge/exercises.py',
    'studyforge/coding.py','studyforge/db.py','studyforge/learning_memory.py','studyforge/server.py',
    'web/help/guide.html','web/mobile/sw.js']
gate.TESTS=['homework_checkpoint','homework_inflight','homework_versions','homework','homework_reader',
    'homework_context','homework_analysis_reuse','homework_recovery_policy','coding','coding_runtime',
    'practice','review_versions','regrade_conditions','assessment_quality','learning_memory','learning_profile',
    'profile_scoring','dialogue_profile_scope','mobile_access','task_retry','task_exercise_workflows',
    'workflow_pause','teaching_review','user_guide']

if __name__=='__main__':gate.main()
