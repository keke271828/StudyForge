"""Offline original-answer review with separate, fallible human inspection."""
import base64
import hashlib
import json
from pathlib import Path
import re

from scripts.build_teaching_comparison import ROOT, TEMPLATE, inline_script
from scripts.eval_teaching_scope import MATH, PHILOSOPHY

B = ROOT / 'build'
BASE = 'teaching-scope-20261013-baseline'
RETRY = 'teaching-scope-20261014-retry'
AUDIT = 'explanation-audit-scope-20261014-1'
AUDIT_RETRY = 'explanation-audit-scope-20261014-retry'


def read(directory):
    return json.loads((B / directory / 'report.json').read_text(encoding='utf-8'))


def response(directory, case, label, note, *, scoped=None):
    row = next(r for r in read(directory) if r['case'] == case and r['status'] == 'completed'
               and (scoped is None or r['scope_provided'] == scoped))
    path = B / directory / row['answer_file']
    text = path.read_bytes().decode('utf-8')
    if scoped is None:
        request = json.loads((B / directory / 'requests.json').read_text(encoding='utf-8'))[case]
    else:
        inputs = json.loads((B / directory / 'inputs.json').read_text(encoding='utf-8'))[case]
        request = {'saved_input': inputs, 'scope_provided': scoped, 'summary_level': 1 if scoped else None,
                   'review_mode': 'fast', 'learning_mode': 'deep', 'explanation_style': 'balanced',
                   'audit_reports': row['audit_reports'],
                   'capture_limit': '保存了输入与调用参数，未逐字抓取底层 HTTP 请求；两组均使用当前审查程序。'}
    return {'case': case, 'arm': directory+('-scoped' if scoped else ''), 'label': label,
            'review': note, 'text': text, 'output': str(path), 'sha256': hashlib.sha256(text.encode()).hexdigest(),
            'request': request, 'metrics': f"{row['seconds']} 秒 · {len(text)} 字符 · deepseek-flash / high · 工具关闭",
            'response_model': None, 'usage': None}


def build():
    r = response
    groups = [
        {'case': 'math', 'title': '追问量词：逐项门槛能否合成统一门槛', 'question': MATH['question'], 'source': MATH['source'],
         'rows': [
             r(BASE, 'math-minimal', '简短提示基线',
               '主要量词、空真解释与1/n例子可读。但“只有有限多个门槛可以取最大”过强：无限指标下的门槛也可能有统一上界，甚至全部相等。不能认定全文合格。'),
             r(RETRY, 'math-production', '当前软件导师规则',
               '直接回应N(n)=n+1，给出统一N=100并核对后续项；明确合并时每个门槛原本就要保证整段尾部。但“取最大值只在一种情况下可用”同样把有限这一充分条件写成必要条件。两种提示均有缺陷，不能宣布软件获胜。'),
         ]},
        {'case': 'philosophy', 'title': '事实与评价：模式差异是否真实', 'question': PHILOSOPHY['question'], 'source': PHILOSOPHY['source'],
         'rows': [
             r(BASE, 'philosophy-minimal', '简短提示基线',
               '主线完整，能直接解释需要评价原则，也保留事实仍有用的三种作用；阅读负担相对小，没有来源定位。此例不支持完整提示一定更好。'),
             r(RETRY, 'philosophy-overview', '软件概览',
               '有主线和适用边界，但对这份很短的原文仍写了六部分并引入元伦理学背景，概览的克制不足；没有因此硬性删改原回答。'),
             r(BASE, 'philosophy-deep', '软件精学',
               '用加班的完整例子比较不同原则，区分事实与规范争论，再给出可迁移的检查过程；篇幅较长，有重复。休谟定位属模型自带补充，试验未联网验证，不作为已核实史料。'),
             r(BASE, 'philosophy-research', '软件研究',
               '除主线外比较法律／习俗／道德意义、替代解释与核实方法，具有研究特征；与精学仍有重叠。部分制度及历史概括需要原始材料支持，不能因有边界小节就认定研究充分。'),
         ]},
    ]
    from scripts.eval_explanation_audit_scope import CASES
    for name in ('math', 'philosophy'):
        case = CASES[name]
        groups.append({'case': name+'_audit', 'title': ('数学' if name=='math' else '哲学')+'：同一讲解是否会被范围审查改坏',
            'question': case['requirements'], 'source': case['source'],
            'rows': [r(AUDIT_RETRY, name, '对照：没有提供任务范围',
                '本次通过，未要求补范围外内容。这个对照没有复现误判；它不是旧版本程序的完整回放。', scoped=False),
                r(AUDIT if name=='math' else AUDIT_RETRY, name, '提供本次范围和详略',
                '本次同样通过，正文保持原样。能确认指定范围的审查实际成功，不能据此宣称质量或速度显著胜出。两组不是学习成效实验。', scoped=True)]})
    failures = []
    for directory in (BASE, RETRY, AUDIT, AUDIT_RETRY, 'actual-teaching-audit-20261014-1', 'actual-teaching-audit-20261014-2'):
        if not (B / directory / 'report.json').exists(): continue
        failures.extend({'round': directory, **row} for row in read(directory) if row['status'] != 'completed')
    for group in groups:
        group['round'] = '原样内容与人工复核'
        group['rows'].sort(key=lambda row: row['sha256'])
    actual = B / 'actual-teaching-audit-20261014-2/report.json'
    if actual.exists() and any(r['status']=='completed' for r in read(actual.parent.name)):
        inputs = json.loads((actual.parent / 'inputs.json').read_text(encoding='utf-8'))['actual_math']
        groups.append({'case': 'actual_math_audit', 'round': '原稿错误的快速审查复测', 'title': '充分条件被写成必要条件：实际原稿复核',
            'question': inputs['requirements'], 'source': inputs['source'],
            'rows': [r(RETRY, 'math-production', '未改动的实际原回答',
                '本组原稿与上方数学样例完全相同；应重点检查“只在一种情况下”的必要性主张。'),
                r(actual.parent.name, 'actual_math', '正常快速审查后的正文',
                '本次一个快速审查请求找出并局部修正了“只在一种情况”的过强表述，未重写全文、未再次独立复核。审查证据又把无限指标族{1,1,…}称为无限集合，措辞错误：该值域集合只有一个元素；正确反例是无限多个门槛都等于1。修订正文没有沿用这句，但审查记录也不能当无误证明。', scoped=True)]})
    payload = json.dumps({'groups': groups, 'count': sum(len(g['rows']) for g in groups), 'failures': failures}, ensure_ascii=False).replace('<', '\\u003c')
    assets = ROOT / 'web/vendor'
    css = (assets / 'katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,'+base64.b64encode((assets/'fonts'/m[1]).read_bytes()).decode()+')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    libraries = '\n'.join(inline_script((assets/f).read_text(encoding='utf-8')) for f in ('marked.js','purify.js','katex.js'))
    html = TEMPLATE.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',payload).replace('__LIBRARIES__',libraries).replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    html = html.replace('原有规则、简短基线、修订规则，以及三种展开方式的实际对照。', '数学追问、哲学三种模式，以及讲解范围审查的真实小样本。')
    start, end = html.index('<div class="notice">'), html.index('</div>', html.index('<div class="notice">'))+len('</div>')
    html = html[:start] + '<div class="notice">实际原生 DeepSeek API 最终回答，未润色，不含内部思考或密钥。内容生成使用相同合成资料；审查对照使用当前程序，将任务范围提供与否作比较，并非历史版本对照。数学原稿在两组中复用，12个展示条目来自11次成功调用。每个方案一次，连接失败另存，新一轮补测不覆盖失败；时序、缓存与网络不同，耗时不用于证明普遍提速。只覆盖短文字材料，不代表扫描教材、视频、长期记忆或真实学习收益。两份数学原回答均有必要性表述错误，保留用于检查，不能当教材定稿。模型补充的历史出处未联网核实。</div>' + html[end:]
    html = html.replace("row.seconds+'秒 · 正文 '+row.output_chars+'字符 · 提示 '+row.input_chars+'字符'",'row.metrics')
    html = html.replace('核对实际请求、用量与原文指纹','查看保存的输入与原文指纹')
    html = html.replace('份原始回答 · ', '个原样展示条目 · ')
    target = B / 'teaching-scope-review-20261014/讲解与审查实际对照.html'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(html,encoding='utf-8')
    target.with_suffix('.json').write_text(json.dumps({'samples':sum(len(g['rows']) for g in groups),
        'groups':len(groups),'failed_sample_calls':len(failures),'private_reasoning_included':False,
        'original_outputs_unchanged':True,'additional_model_calls':0},ensure_ascii=False,indent=2),encoding='utf-8')
    print(target)


if __name__=='__main__': build()
