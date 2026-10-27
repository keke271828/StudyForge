from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/lesson-passage-math-final-20261025-3'
gate.FILES=['web/lesson_passage.js','web/lesson_passage.css','web/help/guide.html','web/mobile/sw.js']
gate.TESTS=['lesson_passage','lesson_focus','lesson_read_request','lesson_feedback','mobile_lesson_feedback',
    'lesson_checks','lesson_quality','lesson_content_check','dialogue_profile_scope','message_focus','teaching_review','user_guide']

if __name__=='__main__':gate.main()
