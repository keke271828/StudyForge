"""Development-only explicit assumptions and per-excerpt review receipts."""
import json
from scripts.review_focus_candidate import index

VERSION='2026-10-15-assumptions-and-claim-decisions-candidate'
ASSUMPTIONS=(
    '按每一段明确给定的前提检查这段的结论。例子、推广或反事实改变条件时，不能从主证明或别段借用更强前提来替它补足依据；'
    '若本段明确保留了更强条件，则应允许使用它，不能因为还提到一个较弱条件就禁止合法的推导。'
    '缺少某个推导依据与结论已经被反例推翻须区分。'
    '一个任意存在的参数不能无说明地固定成某个数值来代替一般证明；明确标为演示的数值假设，只按演示目的核对，不冒充一般证明也不自动判错。'
    '“唯一、必须、不可能”应按实际作用范围核对：便利的默认选择不自动排除其他可行选择。'
    '软件附加的来源定位／既往核查提示不是原教材主张；没有实际核对原标记编号和文本时，不凭自己的重新编号宣布这些提示错误。'
)


def prompt(document):
    receipt=index(document);receipt=dict(receipt,version=VERSION)
    if not receipt['entries']:return '\n本轮的前提核对：'+ASSUMPTIONS,receipt
    blocks=[{'claim_id':i,'section':item['section'],'text':item['text']} for i,item in enumerate(receipt['entries'])]
    text=('\n【需要逐项回应的原句核对表；入选不等于有错】\n'+json.dumps(blocks,ensure_ascii=False)+
        '\n'+ASSUMPTIONS+
        '保留原passed、issues和corrections字段，额外返回claim_checks数组，逐个claim_id各一项：'
        '{"claim_id":0,"status":"supported|defect|uncertain","basis":"简短写明本段前提与结论的关系；若判缺陷给确切反例或推导依据"}。'
        'status=supported可以说明原句在上下文下成立；uncertain说明缺什么条件，不自行补齐。'
        '只有会误导求解或理解的实质缺陷才写入issues；可选改写不判缺陷，软件附加提示不当作教学结论。'
        '逐项核对不能代替对前面完整资料、讲解、例子与总结的检查，未入选不等于已经验证。')
    return text,receipt


def validate(report,receipt):
    expected=set(range(len(receipt['entries'])))
    if not expected:return
    rows=report.get('claim_checks')
    if not isinstance(rows,list) or len(rows)!=len(expected):raise ValueError('原句核对表需逐项回应')
    if any(not isinstance(row,dict) or type(row.get('claim_id')) is not int or row.get('status') not in ('supported','defect','uncertain')
           or not isinstance(row.get('basis'),str) or not row['basis'].strip() for row in rows):raise ValueError('核对项需有编号、状态与具体依据')
    if {row['claim_id'] for row in rows}!=expected:raise ValueError('核对项编号缺失或重复')
