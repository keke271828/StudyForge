"""Verbatim teaching comparisons and audits, with unsuccessful trials retained."""
import base64
import hashlib
import json
import re

from scripts.build_teaching_comparison import ROOT, TEMPLATE, inline_script
from scripts.teaching_inference_candidate import CASES


TEACHING_NOTES = {
    ('causal','short'): '区分随机提醒与实际行为，保留分配效应，示意有明确假设。仍把观察到更高分说成支持正向效应，没有展开抽样不确定性；不能据此认定总体效应方向已确定。',
    ('causal','current'): '主要区分正确，例子具体，没有重现上一轮“通常压小”断言。分配比较与实际行为比较的记号仍容易被初学者混淆；对总体效应方向同样需保留估计不确定性。',
    ('causal','candidate'): '主要区分正确，没有新增稀释方向。结尾“说明…有总效应”仍比单次有限样本分差能支持的结论强；不能当作候选规则稳定改善的证据。',
    ('cauchy','short'): '从单点线性约束走到最低点，给出完整数值对照并处理A=0。内容较长，还扩展到几何和判别式，未表现为提示更短就回答更短。',
    ('cauchy','current'): '明确形式上的坏系数不可能来自实际向量，数值与配方正确。但末句“把交叉项B消掉”容易误导：最低值仍含B²，消去的是可调平方项的贡献。',
    ('cauchy','candidate'): '主线与数值计算正确，但“这组数字当然不一定来自真正的向量”不够准确：给定数据违反柯西，明确不可能来自实际向量。没有稳定优于现有规则。',
    ('testing','short'): '四个已测点、静态推演及边界反例区分较好，计算正确。2332字符，重复较多；这组里短教师规则并未生成最短讲解。',
    ('testing','current'): '解释了所有已测输入只走真分支，完整核对100和相邻值，保留从代码推导出的更强结论。较长且反复总结，仍有压缩空间。',
    ('testing','candidate'): '边界与两个分支均讲清，1731字符，比另外两臂紧凑；但这是单次样本，不能把差异归因于规则或推广为总体质量优势。',
    ('explanation','short'): '有细节，但将观察条件概率差直接写成规则有作用的依据，没有额外因果识别条件；图书馆楼层差异作为例子中的证据，未清楚标明整段为假设。不能只因文字流畅判为合格。',
    ('explanation','current'): '能区分一种机制和排他解释，也强调未排除不等于已证明其他因素。但示意场景缺少清楚的假设标识，额外提出的奖惩方向命题也需限定条件；文字较长。',
    ('explanation','candidate'): '案例转成“为什么迟到”，而制度在案例中主要解释“为什么在意迟到或采取补救”；后文承认差别，但未用同一结果展示多种解释。另有无关的物理比较，且2442字符最长。候选规则不进入应用。',
}


def assets(payload):
    vendor = ROOT/'web/vendor'; css = (vendor/'katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,'+base64.b64encode((vendor/'fonts'/m[1]).read_bytes()).decode()+')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    libraries = '\n'.join(inline_script((vendor/name).read_text(encoding='utf-8')) for name in ('marked.js','purify.js','katex.js'))
    html = TEMPLATE.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', json.dumps(payload, ensure_ascii=False).replace('<','\\u003c'))
    return html.replace('__LIBRARIES__', libraries).replace('__RENDERER__', inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))


def read_exact(path, digest):
    text = path.read_bytes().decode('utf-8')
    if hashlib.sha256(text.encode()).hexdigest()!=digest: raise ValueError('Output fingerprint changed.')
    return text


def main():
    groups, failures = [], []
    teacher = ROOT/'build/teaching-inference-real-20261015-1'
    requests = json.loads((teacher/'requests.json').read_text(encoding='utf-8'))
    results = json.loads((teacher/'results.json').read_text(encoding='utf-8'))
    labels = {'short':'较简短的教师规则', 'current':'现有教师规则', 'candidate':'候选延伸规则（未采用）'}
    for key in ('causal','cauchy','testing','explanation'):
        rows = []
        for arm in labels:
            item = next(row for row in results if row['case']==key and row['arm']==arm)
            if item['status']!='completed': failures.append(item); continue
            text = read_exact(teacher/item['answer_file'], item['answer_sha256'])
            rows.append({'label': labels[arm], 'text': text, 'output': str(teacher/item['answer_file']), 'sha256': item['answer_sha256'], 'review': TEACHING_NOTES[(key,arm)],
                'metrics': f"{item['seconds']}秒 · 正文{item['characters']}字符 · 输入{item['input_characters']}字符",
                'request': {'frozen_input': requests[key+':'+arm], 'call': item}})
        groups.append({'case': key, 'title': CASES[key]['title'], 'round': '教师规则三臂直接对照',
            'question': CASES[key]['question'], 'source': CASES[key]['material'], 'rows': rows})
    replay_folder = ROOT/'build/teaching-inference-20261015/replay'
    replay = json.loads((replay_folder/'results.json').read_text(encoding='utf-8'))
    for folder in (ROOT/'build/inference-audit-real-20261015-1', ROOT/'build/inference-audit-control-20261015-1'):
        inputs = json.loads((folder/'inputs.json').read_text(encoding='utf-8'))
        checked = json.loads((folder/'results.json').read_text(encoding='utf-8'))
        for key, entry in inputs.items():
            rows = []
            for arm in ('current','expanded'):
                item = next(row for row in checked if row['case']==key and row['arm']==arm)
                if item['status']!='completed': failures.append(item); continue
                text = read_exact(folder/item['output_file'], item['output_sha256'])
                note = {'causal': ('未检出两处已知实质问题，原文不变。' if arm=='current' else '同一次快速审查检出两处：把行为比例差混成自选择，以及无条件的稀释方向。提出了修正，但before把直引号改成弯引号，旧守卫未应用，故正文保留疑点提示。'),
                    'explanation':'没有指出例子改变待解释问题的不足。提示词加入这一标准也未稳定检出，仍为漏检；不把它算通过。',
                    'control':('把总结的“可能影响”改成“会影响”，理由是保持原文模态。这个对照的“可能”是否弱化原意存在解释空间，不能当成干净的误报率试验。' if arm=='current' else '没有修改该示意，但不能据此宣称消除误报；这个控制的模态本身有解释空间。'),
                    'math_control':'范围7到17、同向反向端点及不能凭空给概率均保留；这份清楚的范围说明未被修改。'}[key]
                record = json.loads((folder/(key+'-'+arm+'-requests.json')).read_text(encoding='utf-8'))
                rows.append({'label': '现有快速审查' if arm=='current' else '增加结论与例子检查的快速审查',
                    'text': text, 'output': str(folder/item['output_file']), 'sha256': item['output_sha256'], 'review': note,
                    'metrics': f"{item['seconds']}秒 · {item['model_calls']}次模型调用 · 原版守卫的实际交付",
                    'request': {'frozen_review_requests_and_responses': record, 'call': item}})
            if key=='causal':
                item = next(row for row in replay if row['case']==key and row['arm']=='expanded')
                text = read_exact(replay_folder/item['output_file'], item['output_sha256'])
                rows.append({'label':'最终程序回放同一审查返回（没有新增模型调用）', 'text': text, 'output': str(replay_folder/item['output_file']), 'sha256': item['output_sha256'],
                    'review':'两处修正完整应用，保留提醒分配效应并删除无依据的方向判断，实际Word也核对通过。开头“两件事会同时松动随机化的比较”仍可能让人误会为原分组失效；这是残余措辞问题，应用成功不等于整篇再次独立复核通过。',
                    'metrics':'0次额外模型调用 · 2处原有修正应用 · 保留尚未再次复核说明', 'request': item})
            title = {'causal':'已知因果错误：能否检出并修进去', 'explanation':'例子换了问题：仍有漏检',
                     'control':'有解释空间的模态对照', 'math_control':'明确的向量范围对照'}[key]
            groups.append({'case':'audit-'+key, 'title': title, 'round':'同一原稿，现有快速审查与扩展检查',
                'question': entry['requirements'], 'source': entry['source']+'\n\n待审讲解：\n'+entry['draft'], 'rows': rows})
    count = sum(len(group['rows']) for group in groups)
    html = assets({'groups': groups, 'count': count, 'failures': failures})
    html = html.replace('讲解质量：看真实回答，再选规则', '讲解延伸与例子：实测、漏检和最终修正')
    html = html.replace('原有规则、简短基线、修订规则，以及三种展开方式的实际对照。', '对比实际回答，核验结论范围与例子，并保留失败记录。')
    html = html.replace("row.seconds+'秒 · 正文 '+row.output_chars+'字符 · 提示 '+row.input_chars+'字符'", 'row.metrics')
    html = html.replace('核对实际请求、用量与原文指纹', '查看冻结请求、原始审查与正文指纹')
    notice = ('本轮20次教学／审查组件调用：12份直接教学回答，8次已有快速审查。均为同一deepseek-flash / high、合成材料、工具关闭。'
        '每格一次、未盲评，不是完整网页或全应用重放，不作速度或能力排名。教师候选没有稳定优势，未进入应用；'
        '进入应用的是现有审查中的新增结论／例子检查，以及仅普通中文段落双引号样式等价的局部锚点处理。'
        '21个展示项中最后的因果修正是同一返回的程序回放，0次新模型调用；不是又生成了一份更优秀回答。'
        '仍存在换解释对象的漏检、原稿残余措辞，以及原模态对照的解释空间，人工评语逐项说明。'
        '规则指纹只证明请求过这些检查，不认证讲解全对。正文原样保存，不含私有思考、密钥或真实学习记录。'
        '因果识别的背景可参考<a href="https://users.nber.org/~rdehejia/%21%40%24AEM/Topic%2004%20IV/readings/angrist_imbens_rubin_JASA_1996.pdf">Angrist、Imbens与Rubin（1996）</a>第4.1节；本页数字模型是自建反例，不是现实研究结果。')
    start = html.index('<div class="notice">'); end = html.index('</div>', start)+len('</div>')
    html = html[:start]+'<div class="notice">'+notice+'</div>'+html[end:]
    out = ROOT/'build/teaching-inference-20261015'; out.mkdir(parents=True, exist_ok=True)
    path = out/'讲解延伸与例子核查实际对照.html'; path.write_text(html, encoding='utf-8')
    (out/'人工复核与统计.json').write_text(json.dumps({'teaching_component_calls':12, 'audit_component_calls':8,
        'displayed_samples':count, 'groups':len(groups), 'candidate_teacher_policy_adopted':False,
        'expanded_audit_adopted':True, 'historical_responses_replayed':len(replay), 'replay_external_model_requests':0,
        'notes':[{ 'case':g['case'], 'label':r['label'], 'note':r['review']} for g in groups for r in g['rows']],
        'reference': {'title':'Angrist, Imbens and Rubin (1996), Identification of Causal Effects Using Instrumental Variables',
            'url':'https://users.nber.org/~rdehejia/%21%40%24AEM/Topic%2004%20IV/readings/angrist_imbens_rubin_JASA_1996.pdf',
            'scope':'Sections 4.1 and the assumptions separate random assignment from exclusion restriction. Numeric cases here are constructed examples, not empirical effect estimates.'}}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(path)


if __name__=='__main__': main()
