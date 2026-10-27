"""Release-only regression. All fixtures use isolated temporary study data."""
from scripts import verify_repair_selection as gate

gate.OUT = gate.ROOT/'build/release-0.4.6-regression'
gate.FILES = ['package.json','package-lock.json','desktop/main.js','desktop/release-config.json',
    'studyforge/teaching_policy.py','studyforge/review.py','studyforge/knowledge.py',
    'studyforge/conversations.py','studyforge/task_progress.py','web/knowledge.js',
    'web/task_controls.js','web/refined.css','web/help/guide.html','web/mobile/sw.js']
gate.TESTS = ['user_guide','desktop_lifecycle','desktop_notifications','bundle_cuda','update_backup',
    'teaching_data_scope','knowledge_continuity','knowledge','manual_task_retry','reading_task_restore']

if __name__=='__main__': gate.main()
