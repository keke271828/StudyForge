from pathlib import Path
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/reading-restore-final-20261026'
gate.FILES=['studyforge/conversations.py','studyforge/server.py','web/task_controls.js','web/conversations.js',
    'web/app.js','web/knowledge.js','web/help/guide.html','tests/test_reading_task_restore.py',
    'tests/task_conversation_scope.test.js','scripts/smoke_reading_restore.py','scripts/smoke_reading_restore.js']
gate.TESTS=['reading_task_restore','project_conversations','source_scope','manual_task_retry',
    'generation_control','task_exercise_workflows','task_retry','mobile_access']
if __name__=='__main__':gate.main()
