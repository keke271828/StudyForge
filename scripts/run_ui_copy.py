from scripts.run_homework_reader_ui import main
import json
from pathlib import Path
import sys
if __name__=='__main__':
    main('scripts.smoke_ui_copy','scripts/smoke_ui_copy.js')
    report=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]/'ui-report.json'
    assert report.is_file() and json.loads(report.read_text(encoding='utf-8'))['passed'], 'UI receipt is required, not just process exit 0'
