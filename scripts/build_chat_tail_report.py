"""Offline teaching-input review: accepted smaller change and rejected reorder."""
import base64
import hashlib
from html import escape
import json
from pathlib import Path
import re
import shutil
from xml.etree import ElementTree as ET

from scripts.build_teaching_comparison import TEMPLATE, inline_script

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/chat-tail-acceptance-20261017'
TITLE = '导师当前问题与重复提示实际对照'

NOTES = {
    ('plain', 'epsilon'): (
        '正确区分使用全称前提与证明全称命题，也说明取正值的合法性；没有完整重证唯一性。仍多次解释同一个方向，不能把原版一概判成讲不清。',
        '保留全称例示、正值和反向不成立的区别，没有重证邻域和统一N；又引入存在量词对照，996字符仍不算短。此轮较快，但不证明所有问题都能提速。'),
    ('plain', 'causal'): (
        '共同原因、箭头倒向和并存讲得清楚；末尾说原文未交代时间顺序，忽略了“原本”的线索，时间含义仍须谨慎解释。',
        '两条箭头与并存直接接回原例，明确说机制不互斥不等于已证明；保留原有能力也可能是混杂的细分。比原版略短，本次也较快，不把分类当因果验证。'),
    ('full', 'full_chemistry'): (
        '各量、单位推导、0.03 mol/(L·s)及计量与速率模型边界齐全。长达4987字符，补充机理、伪一级等较多；把恒容等列成模型普遍必要条件，超出原资料，不能整体认证正确。',
        '完整要求仍得到展开，单位和数值正确，保留总结；3954字符较短，但本次57.75秒比原版53.54秒更慢。仍把v写成“不是常数”、将模型当正反应项，并加入未由原文给出的适用条件；这些表述需限定，不能认定整篇完全正确。'),
    ('order2', 'epsilon'): (
        '全称例示正确，随后又完整展开邻域、三角不等式和统一阈值，重讲了学生明确说已懂的内容。',
        '虽没有完整重证，仍有实质问题：将全称量词中的ε称为“自由变元”；最后还让学生思考N为什么“必须”取max，既超出不出题要求，也把方便构造说成必要。此候选未保留。'),
    ('order2', 'copy_document'): (
        '完整静态结果和第二项[2]保留，槽位替换与原地修改区分正确；没有声称实机运行，仍有重复。',
        '完整结果同样正确，核心解释没有缺项；多写核对列表与总结，未显示稳定质量优势。该组正常不抵消同一候选数学组的错误。'),
    ('order1', 'epsilon'): (
        '先解释全称例示，但随后又重证开邻域、阈值与三角不等式，1317字符偏长。',
        '983字符，使用已有假设与证明定义的方向正确，没有完整收尾证明。这份较好回答也保留；后续同方案复测出现错误，因此没有仅凭这一次采用。'),
    ('order1', 'copy_document'): (
        '464字符，完整静态结果a=[[1],[2]]、b=[[9],[2]]保留，解释正确、总结重复但不缺项。',
        '487字符，槽位替换解释和第二项[2]正确；稍长且稍慢，不构成稳定改进。此处没有损失完整结果，但不能证明所有文档适合换序。'),
    ('order1', 'causal'): (
        '区分共同原因和结果指回行为，说明可能并存且未验证；有一些重复，仍围绕原例。',
        '篇幅更少，但把“理解快→原本成绩好→有余力”的链写得更确定，原文并未逐条验证这条链。样例没有增加研究作业，仍不能认证因果关系。'),
    ('order1', 'full_chemistry'): (
        '完整计算、单位和计量区别保留；正文5561字符，机理、适用条件等补充很多，部分条件并非原资料给出。',
        '6166字符、更慢，继续引入额外机理和条件。具体要求移到最后没有让这篇更有效率，也没有消除补充中的过度概括；文档换序未采用。'),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    groups, table, total, fingerprints = [], [], 0, 0
    folders = [
        ('chat-tail-real-20261017-1', 'plain', '采用范围 · 普通导师聊天', 'plain_question', '去掉重复尾注：完整系统设定保留'),
        ('chat-tail-real-20261017-2', 'full', '补充边界 · 要求完整讲解', 'plain_question', '去掉重复尾注：完整展开要求保留'),
        ('task-order-real-20261017-2', 'order2', '未采用 · 仅换序正式复测', 'task_last', '未采用候选：具体要求移到最后'),
        ('task-order-real-20261017-1', 'order1', '未采用 · 仅换序先前探索', 'task_last', '未采用候选：相同文字调整顺序'),
    ]
    for folder_name, key, round_label, new_arm, new_label in folders:
        folder = ROOT / 'build' / folder_name
        packet = json.loads((folder / 'cases.json').read_text(encoding='utf-8'))
        results = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
        assert all(r['status'] == 'completed' and r['model_requests'] == 1 for r in results)
        total += len(results)
        for case in packet['cases']:
            by_arm = {r['arm']: r for r in results if r['case'] == case['id']}
            rows = []
            for i, (arm, label) in enumerate((('baseline', '原输入：学生问题后附教学尾注'), (new_arm, new_label))):
                result = by_arm[arm]
                answer_path = folder / result['answer_file']
                raw = answer_path.read_bytes()
                assert hashlib.sha256(answer_path.read_text(encoding='utf-8').encode()).hexdigest() == result['answer_sha256']
                expected = dict(case['request_options'], messages=case['requests'][arm], stream_options={'include_usage': True})
                expected_sha = hashlib.sha256(json.dumps(expected, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                assert result['http_attempts'][0]['body_sha256'] == expected_sha
                fingerprints += 1
                rows.append({'case': key + '-' + case['id'], 'arm': arm, 'label': label, 'text': raw.decode('utf-8'),
                             'review': NOTES[(key, case['id'])][i], 'seconds': round(result['seconds'], 2),
                             'input_chars': sum(len(m['content']) for m in case['requests'][arm]),
                             'output_chars': result['output_characters'],
                             'response_model': result['http_attempts'][0].get('returned_model') or result['model'],
                             'usage': [t['usage'] for t in result['http_attempts']],
                             'sha256': hashlib.sha256(raw).hexdigest(), 'request': case['requests'][arm]})
            source = case['source'] + '\n\n此前导师回答（AI内容，不作原文件证据）：\n' + case['previous']
            if case.get('instructions') and case['role'] == 'lecture':
                source += '\n\n独立文档要求：\n' + case['instructions']
            source += '\n\n预先固定的核对点：\n' + '\n'.join(case['checks'])
            groups.append({'round': round_label, 'case': key + '-' + case['id'], 'title': case['title'],
                           'question': case['question'], 'source': source, 'rows': rows})
            a, b = by_arm['baseline'], by_arm[new_arm]
            table.append('<tr><td>' + escape(round_label) + '</td><td>' + escape(case['title']) + '</td><td>'
                         + f"{a['seconds']:.2f}秒／{a['output_characters']}字符" + '</td><td>'
                         + f"{b['seconds']:.2f}秒／{b['output_characters']}字符" + '</td></tr>')
    assert total == fingerprints == 18 and len(groups) == 9

    latest, suite_counts, initial_failures = {}, {}, 0
    for filename in ('chat-tail-final-regression-20261017.xml', 'chat-tail-delivery-regression-20261017.xml',
                     'chat-tail-final-supplement-20261017.xml'):
        tests = ET.parse(ROOT / 'build' / filename).getroot().findall('.//testcase')
        suite_counts[filename] = len(tests)
        initial_failures += sum(t.find('failure') is not None for t in tests)
        for test in tests:
            latest[(test.get('classname'), test.get('name'))] = test
    assert len(latest) == 223 and all(t.find(k) is None for t in latest.values() for k in ('failure', 'error', 'skipped'))
    ui_folder = ROOT / 'build/chat-tail-ui-20261017-1'
    ui = json.loads((ui_folder / 'ui-results.json').read_text(encoding='utf-8'))
    assert ui['passed'] and len(ui['checks']) == 6 and ui['external_model_requests'] == 0
    for name in ('电脑端原句追问.png', '手机端原句追问.png'):
        shutil.copyfile(ui_folder / name, OUT / name)

    intro = '''<header><div class="eyebrow">STUDYFORGE · CURRENT QUESTION · 2026-10-17</div>
<h1>先让导师收到你的问题，减少每轮重复的教学尾注</h1>
<p><a href="../../验收最新版.vbs">最新版源码验收入口</a> · <a href="../../docs/导师当前问题与重复提示验收.md">详细验收记录</a>。本轮未打包。</p>
<div class="notice">本轮18份真实DeepSeek回答全部原样保留：<strong>12份用于检验换序候选，发现错误后拒绝；另6份用于检验仅删除普通聊天重复尾注的小改动</strong>。共同教学规则、模式、风格、语言、资料和对话仍提供，模型与high推理强度保持。以下不是网页端测试，也不证明所有回答都更好或更快。</div></header>'''
    evidence = '''<details class="prompt"><summary>展开查看采用了什么、拒绝了什么，以及验收范围</summary>
<h2>已采用的较小调整</h2><p>普通聊天原来在学生问题之后，再追加风格提醒、教学任务提醒和模式提醒；同类要求已经在系统设定中提供。本次只去掉当前用户消息末尾的这段重复内容，保留原始问题、选中的历史AI原句、完整系统设定、当前资料、画像和工具。Codex与其他原生模型入口均应用；真实质量对照只测本机配置的DeepSeek Flash／high，工具在两臂都省略。</p>
<p>普通精学样例每轮少275个输入字符，研究样例少223个；这是字符数，不是已测token下降比例。旧聊天第一次使用时按公开记录恢复内部协议，之后继续复用，聊天原话、资料、画像和成果不清空。独立文档生成、审查、批改保持原任务组织，没有把聊天精简套到完整文档，也没有新增固定模型请求。</p>
<h2>为什么拒绝仅调整顺序</h2><p>先用8份回答探索，再用4份带明确换行分隔的正式输入复测。数学候选虽不再从头重证，仍把量词内的ε误称为自由变元，又在不出题要求下追加“为什么N必须取max”的问题。文档化学候选比原版更长更慢。因此撤回换序，保留这些缺陷回答，未挑选较好的单次结果冒充稳定提高。</p>
<h2>采用方案仍有什么不足</h2><p>后续6份回答中，极限与社会科学样例关键解释保留、本次较快；完整化学回答保留单位推导、0.03 mol/(L·s)和总结，字符数少了一些，但耗时更长。两版化学都扩展了原文未给出的条件，新版仍有“v不是常数”等需要限定的表述。少重复提示不能保证正确性、避免一切重讲或实现普遍提速。完整答案和人工评语在下方，均可质疑。</p>
<div class="report-table"><table><thead><tr><th>阶段</th><th>问题</th><th>原输入</th><th>候选／新版</th></tr></thead><tbody>__ROWS__</tbody></table></div>
<p>各对照逐对保留系统内容、资料、历史、模型与推理强度；记录实际HTTP请求指纹18份全部一致。仅删除尾注的三组没有改变原问题和其他消息。请求用量只保存服务返回的计数，不保存私有思考正文。每组每臂一次，探索与正式复测分开；服务缓存、排队和波动会影响耗时。这里只测文本推理，不含视频、扫描OCR或排版。</p>
<h2>程序与完整流程</h2><p>223项最终相关检查通过，覆盖原句引用与原问题、模式与语言切换、画像及跨对话隔离、审批等待、客户端释放、文档生成与来源核对、手机补讲。最初两项未通过：一项旧测试假定内部问题带额外尾注，现已改为验证公开问题保留；另一项发现默认会话指纹仍按旧尾注计算，已同步并复测。保留全部初轮记录，补充33项相关复核按测试标识去重，不重复累计。</p>
<p>受控完整DOCX流程仍实际写出与重读；没有把受控响应当真实云端教学。6项实际Electron电脑／配对HTTPS手机流程通过，包括长回答选句、切换与重开、保存的问题和当前系统设置、后续发送；2次受控模型响应，零次该界面测试外部请求。手机是390px浏览器验收，不代替真实安卓全部流程。</p>
<p>指南与手机壳v54同步。退出旧源码实例后双击上方入口，普通导师聊天即可使用新组织。已安装EXE未因源码变化而自动替换。本轮不宣称全应用RAM或长视频速度问题全部解决。</p>
<details><summary>查看实际电脑与手机宽度截图</summary><p>隔离测试使用固定回答，只验收输入传递和界面行为，不把截图中的受控正文用作教学质量证据。</p>
<figure><img src="电脑端原句追问.png" alt="电脑原句追问保存并恢复"><figcaption>电脑：原始问题、引用和设置按当前对话保存。</figcaption></figure>
<figure><img class="phone-shot" src="手机端原句追问.png" alt="配对HTTPS手机原句追问"><figcaption>配对HTTPS手机宽度：问题传递与继续提问通过。</figcaption></figure></details></details>'''
    evidence = evidence.replace('__ROWS__', ''.join(table))
    page = re.sub(r'<header>.*?</header>', lambda _: intro, TEMPLATE, flags=re.S).replace('<main>', '<main>' + evidence, 1)
    page = page.replace('<title>StudyForge · 讲解质量真实对照</title>', f'<title>{TITLE} · StudyForge</title>')
    page = page.replace('grid-template-columns:repeat(3,minmax(0,1fr))', 'grid-template-columns:repeat(2,minmax(0,1fr))')
    page = page.replace('</style>', '.report-table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border:1px solid #d2e0d6;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}.lesson-math.display-math{display:block;overflow-x:auto;overflow-y:hidden;padding:6px 0}.katex-display{overflow:visible}figure{margin:20px 0}figure img{display:block;max-width:100%;height:auto;border:1px solid #d8e2df;border-radius:12px}figure .phone-shot{max-width:min(100%,390px)}figcaption{font-size:14px;color:#53656a}</style>', 1)
    css = (ROOT / 'web/vendor/katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,' + base64.b64encode((ROOT / 'web/vendor/fonts' / m[1]).read_bytes()).decode() + ')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    page = page.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', json.dumps({'groups': groups, 'count': total, 'failures': []}, ensure_ascii=False).replace('<', '\\u003c'))
    page = page.replace('__LIBRARIES__', '\n'.join(inline_script((ROOT / 'web/vendor' / name).read_text(encoding='utf-8')) for name in ('marked.js', 'purify.js', 'katex.js')))
    page = page.replace('__RENDERER__', inline_script((ROOT / 'web/lesson_render.js').read_text(encoding='utf-8')))
    page = page.replace('查看本次提供的完整合成原资料', '查看合成资料、先前回答及预定核对点')
    page = page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。', '原始回答、公开输入、公式与字体已内嵌，界面截图位于同一文件夹；查看不请求模型。下载指纹对应原始换行。缺陷回答保留用于比较，请勿当定稿教材。')
    target = OUT / f'{TITLE}.html'
    target.write_text(page, encoding='utf-8')
    manifest = {'answers': total, 'groups': len(groups), 'report_table_rows': [len(table)],
                'program_checks': len(latest), 'suites': suite_counts, 'initial_test_failures_resolved': initial_failures,
                'ui_checks': len(ui['checks']), 'real_model_requests': total, 'rejected_order_requests': 12,
                'accepted_tail_requests': 6, 'native_request_fingerprints_matched': fingerprints,
                'shared_teaching_rules_changed': False, 'lecture_task_changed': False, 'package_created': False,
                'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(target), **manifest}, ensure_ascii=True))


if __name__ == '__main__':
    main()
