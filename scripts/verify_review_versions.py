"""Freeze the production changes while checking assessment/review provenance."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/review-versions-final-20261025'
gate.FILES=['studyforge/review_versions.py','studyforge/db.py','studyforge/exercises.py','studyforge/practice.py',
    'studyforge/homework.py','studyforge/learning_profile.py','studyforge/learning_goals.py',
    'studyforge/learning_memory.py','studyforge/task_retry.py','web/practice.js','web/homework.js',
    'web/mobile/homework.js','web/learning_profile.js','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['review_versions','review_queue_lifecycle','practice','navigation','project_purge',
    'learning_goals','learning_transfer','homework','homework_analysis_reuse','homework_recovery_policy',
    'homework_context','homework_reader','regrade_conditions','assessment_quality','assessment_isolation',
    'practice_hint_entry','profile_recency','learning_profile','profile_scoring','learning_memory',
    'task_retry','mobile_access','teaching_review']

if __name__=='__main__':gate.main()
