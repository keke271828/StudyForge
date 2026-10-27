from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/homework-evidence-final-20261026-3'
gate.FILES=['studyforge/homework.py','studyforge/homework_evidence.py','studyforge/homework_analysis.py',
    'studyforge/homework_context.py','web/help/guide.html','web/mobile/sw.js']
gate.TESTS=['homework_evidence','homework','homework_context','homework_reader','homework_analysis_reuse',
    'homework_checkpoint','homework_inflight','homework_versions','homework_recovery_policy','assessment_quality',
    'learning_memory','learning_profile','dialogue_profile_scope','document_exports','nested_math_exports',
    'message_exports','mobile_access','teaching_review','user_guide']

if __name__=='__main__':gate.main()
