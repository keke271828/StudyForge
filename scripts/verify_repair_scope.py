"""Final source-frozen regression gate for private original-target propagation."""
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/repair-scope-final-20261022-2'
gate.FILES=['studyforge/exercises.py','studyforge/repair_learning.py']
gate.TESTS=['repair_scope','repair_selection','repair_learning','generation_review_recovery',
            'parallel_exercise_reviews','task_exercise_workflows','assessment_quality',
            'learning_transfer','learning_goals','lesson_checks']

if __name__=='__main__':gate.main()
