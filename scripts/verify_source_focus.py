from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/source-focus-final-20261026-2'
gate.FILES=['studyforge/server.py','studyforge/source_focus.py','studyforge/teaching_policy.py',
            'web/help/guide.html','web/mobile/sw.js']
gate.TESTS=['source_focus','chat_source_focus','source_request_scope','source_scope','source_origins','source_preparation',
    'original_generation','direct_source_parsing','message_focus','chat_client_cleanup','chat_approval_wait',
    'dialogue_profile_scope','teaching_session_state','teaching_preferences','teaching_context','teaching_review',
    'reading_note_inputs','lesson_quality','learning_modes','explanation_review_scope','mobile_access','user_guide']

if __name__=='__main__':gate.main()
