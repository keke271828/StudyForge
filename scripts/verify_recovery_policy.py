"""Relevant immutable-source gate for recovery choice and attempt delivery."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/recovery-policy-final-20261023-2'
gate.FILES=['studyforge/homework.py','web/homework.js','web/mobile/homework.js',
    'web/mobile/index.html','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['homework_recovery_policy','practice_hint_entry','practice','homework','homework_context',
    'homework_reader','homework_analysis_reuse','learning_profile','profile_scoring',
    'mobile_access','teaching_review','repair_selection']

if __name__=='__main__':gate.main()
