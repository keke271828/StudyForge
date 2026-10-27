from scripts import verify_repair_selection as gate
gate.OUT=gate.ROOT/'build/knowledge-continuity-final-20261026'
gate.FILES=['studyforge/server.py','studyforge/task_progress.py','web/knowledge.js','web/task_controls.js','web/refined.css']
gate.TESTS=['knowledge_continuity','knowledge','workspace_polling','reading_task_restore','project_conversations',
            'manual_task_retry','generation_control','task_exercise_workflows','mobile_access']
if __name__=='__main__':gate.main()
