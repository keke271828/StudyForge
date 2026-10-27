"""Final focused gate for optional hints and immutable submission evidence."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/practice-hints-final-20261023'
gate.FILES=['studyforge/practice.py','studyforge/homework.py','studyforge/homework_context.py',
    'studyforge/mobile_access.py','web/practice_hints.js','web/practice_hints.css','web/homework.js',
    'web/mobile/homework.js','web/index.html','web/mobile/index.html','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['practice_hint_entry','practice','homework','homework_context','homework_reader',
    'homework_analysis_reuse','learning_profile','profile_scoring','mobile_access','teaching_review','repair_selection']

if __name__=='__main__':gate.main()
