import json,sys
from pathlib import Path
from scripts.run_homework_reader_ui import main
if __name__=='__main__':
    main('scripts.smoke_knowledge_continuity','scripts/smoke_knowledge_continuity.js')
    result=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]/'ui-report.json'
    assert result.is_file() and json.loads(result.read_text(encoding='utf-8'))['passed']
