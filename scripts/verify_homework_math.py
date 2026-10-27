from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/homework-math-final-20261025-2'
gate.FILES=['web/practice.js','web/app.js','web/homework.js','web/mobile/homework.js',
    'web/assessment.css','web/mobile/style.css','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['homework','homework_reader','homework_context','homework_analysis_reuse','homework_recovery_policy',
    'practice','repair_learning','repair_readiness','review_versions','assessment_quality',
    'dialogue_profile_scope','mobile_access','teaching_review','user_guide']

if __name__=='__main__':gate.main()
