from scripts import verify_repair_selection as gate

gate.OUT = gate.ROOT/'build/teaching-data-scope-final-20261026-1'
gate.FILES = ['studyforge/teaching_policy.py', 'studyforge/review.py', 'studyforge/teaching.py',
    'studyforge/ai.py', 'studyforge/server.py', 'studyforge/learning_modes.py',
    'studyforge/teaching_styles.py', 'studyforge/source_focus.py', 'studyforge/message_focus.py']
gate.TESTS = ['teaching_data_scope', 'teaching', 'teaching_preferences', 'teaching_context',
    'teaching_session_state', 'learning_modes', 'source_focus', 'chat_source_focus',
    'dialogue_profile_scope', 'inference_audit', 'explanation_review_scope', 'review_modes',
    'review_input', 'review_correction_groups', 'review_quote_anchors']

if __name__ == '__main__': gate.main()
