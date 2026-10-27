"""Freeze the rendered citation reader while checking reference boundaries."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/message-math-final-20261025'
gate.FILES=['web/source_selection.js','web/lesson_render.js','web/message_focus.js','web/message_focus.css',
    'web/index.html','web/mobile/index.html','web/mobile/sw.js','studyforge/mobile_access.py','web/help/guide.html']
gate.TESTS=['message_focus','message_exports','message_history_pages','library_followup_focus','lesson_passage',
    'lesson_focus','lesson_read_request','lesson_feedback','mobile_lesson_feedback','mobile_access',
    'dialogue_profile_scope','teaching_review']

if __name__=='__main__':gate.main()
