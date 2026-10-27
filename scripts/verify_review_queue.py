"""Frozen regression gate for review queue scope and recycle lifecycle."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/review-queue-final-20261025'
gate.FILES=['studyforge/practice.py','studyforge/server.py','web/practice.js','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['review_queue_lifecycle','practice','navigation','project_purge','learning_goals','learning_transfer',
    'homework','homework_recovery_policy','homework_context','homework_reader','regrade_conditions',
    'assessment_quality','practice_hint_entry','repair_readiness','profile_recency','mobile_access','teaching_review']

if __name__=='__main__':gate.main()
