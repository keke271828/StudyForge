"""One frozen final gate for chat-evidence attribution and downstream teaching."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/learning-voice-final-20261023'
gate.FILES=['studyforge/learning_voice.py','studyforge/learning_signals.py','studyforge/learning_memory.py',
            'studyforge/learning_profile.py','studyforge/db.py','web/help/guide.html','web/mobile/sw.js']
gate.TESTS=['learning_voice','learning_memory','learning_profile','dialogue_profile_scope','profile_focus',
            'profile_scoring','lesson_content_check','lesson_content_rounds','homework_analysis_reuse',
            'repair_scope','repair_learning','project_purge','mobile_access','teaching_review']

if __name__=='__main__':gate.main()
