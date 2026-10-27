from scripts.run_homework_reader_ui import main
import json
from pathlib import Path
import sys
if __name__=='__main__':
    main('scripts.smoke_error_help','scripts/smoke_error_help.js')
    receipt=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]/'ui-report.json'
    assert receipt.is_file() and json.loads(receipt.read_text(encoding='utf-8'))['passed']
