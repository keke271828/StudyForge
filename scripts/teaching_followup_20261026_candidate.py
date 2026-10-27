"""Frozen, narrow follow-up experiment; not a deployed prompt."""
from studyforge.teaching_policy import REASONING_TEACHING_RULES, DATA_SCOPE_RULES
from scripts.teaching_followup_candidate import CASES as ORIGINAL_CASES

VERSION='2026-10-26-current-request-known-parts'
FOCUSED_RULE=(
    '本次明确说某部分已懂、只补某一步时，把篇幅用于剩下的理由或操作；'
    '只回顾接通它所必需的内容，不重讲已懂部分、完整证明或平行解法，也不另作全文总结。'
    '本次要求系统展开时则完整展开，不受先前短追问限制。'
)
BASELINE_RULES=REASONING_TEACHING_RULES.removesuffix(DATA_SCOPE_RULES)
RULES=BASELINE_RULES+FOCUSED_RULE
CASES=[item for item in ORIGINAL_CASES if item['id'] in ('epsilon_instance','copy_slot','causal_mechanisms','full_chemistry')]
