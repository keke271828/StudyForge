"""Recheck an unchanged actual math answer through the normal fast review."""
import asyncio
from pathlib import Path
import sys

from scripts import eval_explanation_audit_scope as probe
from scripts.eval_teaching_scope import MATH


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    draft = root / 'build/teaching-scope-20261014-retry/math-production.md'
    probe.CASES = {'actual_math': {'source': MATH['source'], 'requirements': MATH['question'],
                                  'draft': draft.read_text(encoding='utf-8')}}
    asyncio.run(probe.main(sys.argv[1], ('actual_math:scoped',)))
