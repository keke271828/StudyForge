"""Frozen regression gate for recent evidence and historical-doubt context."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/profile-recency-final-20261023-3'
gate.FILES=['studyforge/learning_profile.py','studyforge/learning_memory.py','web/learning_profile.js',
    'web/learning_profile.css','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['profile_recency','learning_profile','profile_scoring','profile_focus','dialogue_profile_scope',
    'learning_memory','learning_context','learning_flow','learning_modes','learning_voice',
    'homework','homework_analysis_reuse','regrade_conditions','assessment_quality','practice',
    'repair_readiness','mobile_access','teaching_review']

if __name__=='__main__':gate.main()
