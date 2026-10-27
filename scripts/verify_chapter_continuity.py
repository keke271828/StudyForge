from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/chapter-continuity-final-20261026'
gate.FILES=['studyforge/source_origins.py','studyforge/lesson_quality.py','web/help/guide.html','web/mobile/sw.js']
gate.TESTS=['chapter_continuity','task_scheduling','parallel_review','generation_control','generation_review_recovery',
    'generation_progress','source_origins','source_preparation','original_generation','lesson_quality','reading_note_inputs',
    'summary_cautions','teaching_review','user_guide','mobile_access','source_focus','chat_source_focus',
    'explanation_review_scope','task_exercise_workflows']

if __name__=='__main__':gate.main()
