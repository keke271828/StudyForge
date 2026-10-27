"""Final source-frozen grading, profile and delivery regression gate."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/regrade-conditions-final-20261023'
gate.FILES=['studyforge/exercises.py','studyforge/homework.py','studyforge/learning_memory.py','studyforge/learning_profile.py',
    'web/practice.js','web/homework.js','web/mobile/homework.js','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['regrade_conditions','assessment_quality','assessment_isolation','homework_recovery_policy',
    'practice_hint_entry','practice','homework','homework_context','homework_reader','homework_analysis_reuse',
    'learning_profile','learning_memory','profile_scoring','mobile_access','teaching_review','repair_selection']

if __name__=='__main__':gate.main()
