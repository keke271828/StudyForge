"""Small teaching hypothesis after a real unsupported initial-condition claim."""
from studyforge.teaching_policy import REASONING_TEACHING_RULES, DATA_SCOPE_RULES
from scripts.teaching_followup_candidate import CASES as ORIGINAL_CASES
VERSION='2026-10-26-preserve-given-data-status'
DATA_SCOPE_RULE=DATA_SCOPE_RULES
# Keep the pre-change comparison after deployment. Frozen cases.json remains
# the authority for the already completed experiment, including other policies.
BASELINE_RULES=REASONING_TEACHING_RULES.removesuffix(DATA_SCOPE_RULE)
RULES=BASELINE_RULES+DATA_SCOPE_RULE
CASES=[next(item for item in ORIGINAL_CASES if item['id']=='full_chemistry'),
 {'id':'reading_survey','title':'社会调查：自愿填写者的均值能说明谁','role':'tutor','style':'clear','mode':'deep','phase':'heldout',
  'source':'某班共有60名学生。一次课后有20名学生自愿填写问卷，他们自报昨天课外阅读时长的平均值为30分钟。资料没有给未填写者的数据，也没有抽样设计或长期记录。',
  'question':'请把这条调查结果解释清楚：30分钟到底是谁、哪段时间的什么平均值，能据此了解什么，不能推广到什么？可以举一个完整的具体例子帮助理解，不布置习题。',
  'checks':['只描述20名自愿填写者昨天自报时长的算术平均','不把该均值变成全班或长期习惯','缺少未填写者的数据，不假定随机代表','完整例子标为假设，不当成真实个体记录','不要求先做题也不附待答练习']}]
