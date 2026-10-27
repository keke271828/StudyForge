"""Offline acceptance of current-question profile retrieval and live samples."""
import base64
import hashlib
from html import escape
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

from scripts.build_teaching_comparison import TEMPLATE, inline_script

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/profile-focus-acceptance-20261016'
NOTES = {
    (1, 'gauss_quote'): (
        '正确区分净通量与局部场，用外部点电荷说明可以进出抵消。但连用球内外点电荷、正负电荷三个情形，没有把某个曲面算完整；没有收到当前卡点画像。',
        '按新增的相关画像，用匀强场穿过立方体，逐面计算−E₀L²、+E₀L²与四个0，直观更贴近自报困难。仍有重复收束；“被积函数是E·dA”宜准确区分E·n与通量微元。不能把更快的一次当普遍速度。'),
    (1, 'epsilon_book'): (
        '全称命题使用特例的方向正确，正半径、两个阈值和严格三角不等式均正确。但又完整重证、给数值邻域、重复总结，1753字符明显偏长。',
        '开头更明确区分使用已知全称命题与证明极限，仍完整重证邻域、最大门槛和三角不等式，没有充分照顾已自报理解这些部分的画像。1706字符，仅略短，不能认定冗长已解决。'),
    (1, 'copy_document'): (
        '槽位替换、共享内层与完整两元素结果正确，未称已运行；文档有总结。两幅图、结果和总结仍有重复。',
        '结果和对象关系均正确，第二项[2]保留，没有复现上一轮提示词候选的漏项。但1175字符比原版1129字符更多，本次也更慢；画像进入输入并不保证输出更简洁。'),
    (2, 'gauss_quote'): (
        '积分值与逐点场的区分正确，外法线和正负号说明清楚；球面匀强场只是理想示意，未逐面给出可跟算的数值关系。',
        '用立方体六面通量计算具体回应自报困难，说明其余四面通量零而场不为零，并接回积分抵消。主要公式正确，较易跟算；1061字符比原版664字符长，末尾仍重复，不把更长本身当更优。'),
    (2, 'epsilon_book'): (
        '使用全称命题、半径上界与开区间等号、统一阈值均讲清。1718字符又重证完整矛盾，已经理解部分占篇幅；n≥N是合法等价阈值写法，不能仅凭与资料n>N不同就判错。',
        '1619字符，先区分“应用已有定义”和“只验证一个值证明极限”，关键逻辑正确；仍重讲邻域和统一N，本次更慢。引文将原文字句改成LaTeX及新标点，不能视为逐字引用。画像检索修好不代表这类讲解已达理想。'),
    (2, 'copy_document'): (
        '839字符，正确解释只替换b的第0槽位，完整结果a=[[1],[2]]、b=[[9],[2]]正确；类比和总结服务同一操作，但有重复。',
        '755字符，完整结果与引用图正确，第二项保留，文档独立可读并有总结，没有声称实机执行。此例较短且更快，不过仍回顾了学生自报已知的浅复制关系，不作为所有场景胜出证明。'),
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    groups, table, requests = [], [], 0
    # The formal native replay is shown first. Keep the earlier exploration too.
    for round_no in (2, 1):
        folder = ROOT / f'build/profile-focus-real-20261016-{round_no}'
        packet, results = load(folder / 'cases.json'), load(folder / 'results.json')
        assert len(results) == 6 and all(r['status'] == 'completed' and r['model_requests'] == 1 for r in results)
        requests += sum(r['model_requests'] for r in results)
        for case in packet['cases']:
            by_arm = {r['arm']: r for r in results if r['case'] == case['id']}
            assert case['observation'] not in case['contexts']['before'] and case['observation'] in case['contexts']['after']
            rows = []
            for index, (arm, label) in enumerate((('baseline', '原检索：当前卡点记录缺失'), ('focused', '新检索：优先本次问题和原句'))):
                row = by_arm[arm]; path = folder / row['answer_file']
                raw = path.read_bytes()
                assert hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest() == row['answer_sha256']
                if round_no == 2:
                    expected = dict(case['request_options'], messages=case['requests'][arm], stream_options={'include_usage': True})
                    digest = hashlib.sha256(json.dumps(expected, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    assert row['http_attempts'][0]['body_sha256'] == digest
                rows.append({
                    'case': str(round_no) + '-' + case['id'], 'arm': arm, 'label': label,
                    'text': raw.decode('utf-8'), 'review': NOTES[(round_no, case['id'])][index],
                    'seconds': round(row['seconds'], 2), 'output_chars': row['output_characters'],
                    'input_chars': sum(len(m['content']) for m in case['requests'][arm]),
                    'response_model': row['model'], 'usage': [t['usage'] for t in row['http_attempts']],
                    'sha256': hashlib.sha256(raw).hexdigest(), 'request': case['requests'][arm],
                })
            a, b = by_arm['baseline'], by_arm['focused']
            table.append('<tr><td>' + ('正式' if round_no == 2 else '探索') + '</td><td>' + escape(case['title']) + '</td><td>'
                         + f"{a['seconds']:.2f}秒／{a['output_characters']}字符" + '</td><td>'
                         + f"{b['seconds']:.2f}秒／{b['output_characters']}字符" + '</td></tr>')
            source = case['source'] + '\n\n此前AI回答：\n' + case['previous']
            source += '\n\n合成的目标画像（不是对真实用户的评定）：\n' + case['observation']
            source += '\n\n原检索实际送入的画像摘要：\n' + case['contexts']['before']
            source += '\n\n新检索实际送入的画像摘要：\n' + case['contexts']['after']
            source += '\n\n采样前核对点：\n' + '\n'.join(case['checks'])
            groups.append({
                'round': '正式原生输入' if round_no == 2 else '先前探索 · 边界重复',
                'case': str(round_no) + '-' + case['id'], 'title': case['title'],
                'question': case['question'], 'source': source, 'rows': rows,
            })
    checks, suites = set(), {}
    for name in ('profile-focus-final-regression-20261016.xml', 'profile-focus-delivery-regression-20261016.xml',
                 'profile-focus-guide-final-20261016.xml'):
        rows = ET.parse(ROOT / 'build' / name).getroot().findall('.//testcase')
        assert rows and all(r.find(k) is None for r in rows for k in ('failure', 'error', 'skipped'))
        suites[name] = len(rows); checks.update((r.get('classname'), r.get('name')) for r in rows)
    intro = '''<header><div class="eyebrow">STUDYFORGE · LEARNER CONTEXT · 2026-10-17</div>
<h1>导师收到的画像，要先对准你当前的卡点</h1>
<p>修复引用追问漏取画像、长资料挤掉当前知识点的问题。<a href="../../验收最新版.vbs">源码验收入口</a> · <a href="../../docs/当前卡点画像检索与教学适配验收.md">详细验收记录</a>。本轮未打包。</p>
<div class="notice">本次修改已有画像的检索，不新增共同教学提示词、不自动评分。以下用<strong>合成资料、对话和自报画像</strong>做3题正式对照及3题探索，完整保留12份真实回答；不是对你本人能力的评定。当前知识点记录能进入输入，模型仍可能重复已懂内容。先看原始回答，再展开方案和评价。</div></header>'''
    evidence = '''<details class="prompt"><summary>已实现什么、怎样测试，以及仍然存在的问题</summary>
<h2>修复前实际复现了两个缺口</h2><ol><li>引用“高斯定律”后只问“这句为什么”，原画像查询只拿到了泛指问题，没有用所选原句定位已有知识记录。</li><li>一本资料或历史对话提到很多知识点时，原筛选按更新先后取有限条数，当前问题的旧记录会被其他较新记录挤掉。</li></ol>
<h2>新的检索顺序</h2><p>聊天依次优先当前问题、明确选中的AI原句，再补充所选资料中的其他相关记录。文档先用本次独立要求，再用冻结对话最后一条学生问题和原句；不会把整段旧聊天里的所有话题都当作当前重点。每层内沿用原顺序，画像摘要仍最多8个知识点，长度上限保持；数值评估参考也优先当前知识点。</p>
<p>匹配依赖已记录的知识点名与关联词，不保证识别全部同义表达。画像总览、默认工具分页、用户纠正与移出记录继续生效。引用AI原句只作检索线索；学生问题原样保存，未把引用改成学生观点，不新增评分、额外画像判断或固定模型请求。正常有学习意义的问题仍可按原流程进入候选队列。</p>
<h2>正式对照与探索的区别</h2><p>DeepSeek Flash／high，使用本机隔离资料和画像。正式轮捕获实际客户端HTTP消息，仅替换画像摘要，核对发出请求的指纹与预期消息、选项一致；两臂都省略工具，正常教学规则、模型、推理强度、资料和用户问题保持相同。2份导师输入、1份文档输入，每臂各一次，共6次真实请求。没有额外审核、排版、视频或扫描识别。</p>
<p>先前探索另6次请求同样只比较画像，但通过Agent客户端再次重放，导致公共上下文边界被重复追加。两臂仍保持相同边界；这轮作为探索保留，不与正式轮混成重复采样，也不据此统计稳定胜率。两轮共12次真实请求、6次本机受控输入捕获，未保存私有推理正文。</p>
<div class="report-table"><table><thead><tr><th>轮次</th><th>问题</th><th>原检索</th><th>新检索</th></tr></thead><tbody>__TIMES__</tbody></table></div>
<h2>人工判断</h2><p>正式高斯样例中，新版沿画像中的具体困难完成立方体六面通量计算，直观更可跟算；它也比原版更长。极限样例逻辑基本正确，但两版都重复了已知的邻域与阈值，新版这次更慢；不能说冗长已解决。编程样例两版完整结果正确，正式新版较短，探索新版却略长。这里更可靠的验收结论是<strong>当前卡点的已有记录不再漏取或被挤出</strong>，不是所有回答都更好、更快。</p>
<h2>完整交付及程序检查</h2><p>__CHECKS__项最终相关去重检查通过。先复现原版缺失，再验证优先顺序、关联词、分页、用户纠正／移出、画像总览、评分原样、跨项目共享摘要与聊天隔离。实际导师调用收到相关记录，原学生问题和分数保持；原始证据引句、其他项目聊天不进入请求。</p>
<p>受控完整DOCX任务使用实际客户端与真实Word输出：多知识点原文、冻结对话和所选原句完整提供，目标画像优先，任务启动后的聊天不混入；1次受控请求生成文件并重新读取正文，不出题、不新增掌握分。其余相关检查覆盖手机补讲入口、任务暂停续接、偏好与原句恢复。未重新验收所有模型账号或真实安卓设备，本轮没有修改产品控件布局。</p>
<p>指南与手机缓存壳v52同步。完全退出旧源码实例后，双击<a href="../../验收最新版.vbs">验收最新版</a>；已有画像会直接使用新检索顺序，无需重新记录。查看全部画像仍可问“我的学习画像是什么”。本轮未证明全软件RAM或长视频速度已解决，安装包仍为原内容。</p></details>'''
    evidence = evidence.replace('__TIMES__', ''.join(table)).replace('__CHECKS__', str(len(checks)))
    page = re.sub(r'<header>.*?</header>', lambda _: intro, TEMPLATE, flags=re.S).replace('<main>', '<main>' + evidence, 1)
    page = page.replace('<title>StudyForge · 讲解质量真实对照</title>', '<title>当前卡点画像与教学适配实际对照 · StudyForge</title>')
    page = page.replace('grid-template-columns:repeat(3,minmax(0,1fr))', 'grid-template-columns:repeat(2,minmax(0,1fr))')
    page = page.replace('</style>', '.report-table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border:1px solid #d2e0d6;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}.lesson-math.display-math{display:block;overflow-x:auto;overflow-y:hidden;padding:6px 0}.katex-display{overflow:visible}</style>', 1)
    css = (ROOT / 'web/vendor/katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,' + base64.b64encode((ROOT / 'web/vendor/fonts' / m[1]).read_bytes()).decode() + ')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    page = page.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', json.dumps({'groups': groups, 'count': 12, 'failures': []}, ensure_ascii=False).replace('<', '\\u003c'))
    page = page.replace('__LIBRARIES__', '\n'.join(inline_script((ROOT / 'web/vendor' / n).read_text(encoding='utf-8')) for n in ('marked.js', 'purify.js', 'katex.js')))
    page = page.replace('__RENDERER__', inline_script((ROOT / 'web/lesson_render.js').read_text(encoding='utf-8')))
    page = page.replace('查看本次提供的完整合成原资料', '查看合成资料、目标画像及实际前后检索摘要')
    page = page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。', '原始正文、公开输入、公式与字体已内嵌，查看不请求模型。正文字符按模型文本统计，下载保留Windows换行，指纹对应下载文件。实验仍有不足，请勿当定稿教材。')
    target = OUT / '当前卡点画像与教学适配实际对照.html'
    target.write_text(page, encoding='utf-8')
    (OUT / 'manifest.json').write_text(json.dumps({
        'answers': 12, 'groups': 6, 'report_table_rows': [6], 'program_checks': len(checks), 'suites': suites,
        'real_model_requests': requests, 'formal_model_requests': 6, 'exploratory_model_requests': 6,
        'controlled_capture_requests': 6, 'native_request_fingerprints_matched': 6, 'package_created': False,
        'shared_teaching_policy_changed': False, 'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(target), 'checks': len(checks), 'real_requests': requests}, ensure_ascii=True))


if __name__ == '__main__':
    main()
