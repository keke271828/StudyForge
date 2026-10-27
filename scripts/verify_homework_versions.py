from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/homework-version-final-20261026'
gate.FILES=['studyforge/homework.py','studyforge/homework_context.py','web/homework.js','web/homework_reader.js',
    'web/app.js','web/mobile/homework.js','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['homework_versions','homework','homework_reader','homework_context','homework_analysis_reuse',
    'homework_recovery_policy','practice','repair_learning','repair_selection','review_versions',
    'assessment_quality','dialogue_profile_scope','mobile_access','teaching_review','user_guide']

if __name__=='__main__':gate.main()
