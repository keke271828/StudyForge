"""Final frozen regression gate for diagnosis readiness and explicit recovery."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/repair-readiness-final-20261023'
gate.FILES=['studyforge/repair_learning.py','studyforge/homework.py','studyforge/server.py',
    'web/practice.js','web/homework.js','web/mobile/homework.js','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['repair_readiness','repair_learning','repair_selection','repair_scope',
    'homework','homework_analysis_reuse','homework_reader','homework_context','practice',
    'assessment_quality','assessment_isolation','homework_recovery_policy','regrade_conditions',
    'practice_hint_entry','mobile_access','teaching_review','task_retry','navigation','task_exercise_workflows']

if __name__=='__main__':gate.main()
