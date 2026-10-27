from scripts import verify_repair_selection as gate
gate.OUT=gate.ROOT/'build/knowledge-questions-final-20261026-2'
gate.FILES=['web/knowledge.js','web/help/guide.html','studyforge/learning_signals.py','studyforge/learning_voice.py','studyforge/knowledge.py']
gate.TESTS=['knowledge','knowledge_continuity','learning_voice','learning_memory','reading_note_inputs','user_guide']
if __name__=='__main__':gate.main()
