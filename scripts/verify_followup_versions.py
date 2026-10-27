"""Freeze follow-up teaching and rate-error UI changes for the final gate."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/followup-versions-final-20261025'
gate.FILES=['studyforge/review_versions.py','studyforge/repair_learning.py','studyforge/learning_goals.py',
    'studyforge/learning_profile.py','studyforge/codex_bridge.py','studyforge/server.py',
    'web/learning_profile.js','web/parallel.js','web/app.js','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['followup_versions','codex_rate_error','review_versions','repair_learning','repair_readiness','repair_selection',
    'learning_goals','learning_transfer','homework','homework_context','homework_reader','profile_recency',
    'profile_focus','learning_profile','task_retry','chat_approval_wait','chat_client_cleanup','dialogue_profile_scope',
    'assessment_isolation','deepseek_standalone','mobile_access','teaching_review']

if __name__=='__main__':gate.main()
