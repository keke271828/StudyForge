"""Replay saved quotation problems and local boundaries without model calls."""
import base64
import hashlib
from html import escape
import json
from pathlib import Path
import re
import shutil
from statistics import median
from time import perf_counter
from xml.etree import ElementTree as ET

from scripts.build_teaching_comparison import TEMPLATE, inline_script
from studyforge.lesson_quality import annotate_chat_quotes, citation_checks

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/quote-provenance-acceptance-20261017'
TITLE = '原文引语与转述核对实际对照'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def saved_case(folder, case_id, arm, title, review):
    folder = ROOT / 'build' / folder
    packet = json.loads((folder / 'cases.json').read_text(encoding='utf-8'))
    case = next(c for c in packet['cases'] if c['id'] == case_id)
    answer = folder / f'{case_id}-{arm}-final.md'
    source = folder / f'{case_id}.txt'
    original = source.read_bytes()
    text = source.read_text(encoding='utf-8')
    return {
        'id': case_id, 'title': title, 'kind': '已保存真实回答回放',
        'question': case['question'], 'source': text,
        'text': answer.read_bytes().decode('utf-8'),
        'records': [{'name': source.name, 'segments': [{'locator': f'行1-{len(text.splitlines())}', 'text': text}]}],
        'review': review, 'origin': str(answer.relative_to(ROOT)),
        'source_path': str(source.relative_to(ROOT)),
        'source_sha256': hashlib.sha256(original).hexdigest(),
    }


def boundary(case_id, title, text, source, review, selected=True):
    return {'id': case_id, 'title': title, 'kind': '本机边界样例 · 无模型调用',
            'question': '本机字符串与来源边界检查；这是有意构造的样例，不是模型新回答或定稿教材。',
            'source': source if selected else '本次没有选择这份来源，也没有自动读取未选文件。',
            'text': text, 'records': [{'name': '案例.txt', 'segments': [{'locator': '行1', 'text': source}]}] if selected else [],
            'review': review, 'origin': '本报告合成的本机边界样例'}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [
        saved_case('profile-focus-real-20261016-2', 'epsilon_book', 'focused',
                   '真实旧回答：把排版后的公式称为原话',
                   '实际旧回答把原文的纯文本公式、字句与标点改成LaTeX后，仍写“原资料那句话是”。本机能唯一找到指定来源，但没有逐字匹配；新版在正文前说明可能是改写或格式差异。完整回答原样保留，本次没有重新调用模型，也不把未匹配判成数学错误。'),
        saved_case('followup-focus-real-20261016-1', 'full_chemistry', 'compact',
                   '真实旧回答：逐字引文不额外打断',
                   '这一处引用与所选原文逐字一致，新旧交付完全相同，不添加聊天核对提示。整份旧讲解来自先前未采用的候选，仍有冗长等问题；这里只核验该引用，不认证整篇教学质量、所有公式或模型优劣。'),
        boundary('whitespace', '空白变化：ab 与 a b 不能叫逐字相同',
                 '原文说：\n\n> 变量名为a b。\n>\n> [案例.txt｜行1]\n\n这份有意构造的示例把原文变量名拆开了。去掉空白会显示匹配，但空白可能改变名称、公式、代码或词义，因此不能把旧统计叫作逐字一致。',
                 '变量名为ab。',
                 '仅删除空白后能匹配；新统计单列“仅忽略空白匹配”，聊天也注明不能视为逐字确认。没有擅自把引用中的空格删掉或把变动判为无害。'),
        boundary('unselected', '来源未选择：提示待核对，不越权读取',
                 '原文指出：\n\n> 这是结论。[未选教材.pdf｜第99页]\n\n这是一份故意没有提供对应来源的边界样例。软件只能说明当前没有唯一可识别的位置，不能据此断言引语是编造的，也不能为了消掉提示自动打开未选文件。',
                 '', '来源没有在本次选材内，无法确认；新版给出定位提示。记录没有变成“已核实”，也没有自动扩展到其他项目、文件或网络。', selected=False),
        boundary('own_example', '导师自己的逻辑示意：不当成教材引语',
                 '一个自己的逻辑示意：\n\n> ∀ε>0 P(ε) ⇒ P(ε₀)\n\n这是这里给出的说明：如果一个性质对所有正数都成立，就能用于其中一个合法的正数。这一段没有声称逐字引自教材，不应只因用了引用块就弹出原文核对提示。',
                 '本次资料提供一个一般逻辑主题。',
                 '没有来源定位，也未声称这是原文。聊天保持原样，避免把导师自己的示例或强调文字一律当成失配引文。该跳过规则不等于认证逻辑证明。'),
        boundary('omission', '省略号边界：片段相同仍可能漏掉条件',
                 '原文说：\n\n> 结论：[…]方程ax=1有唯一解x=1/a。[案例.txt｜行1]\n\n这是故意删去关键条件的反面样例。仅按字符与顺序核对，仍可能显示引用片段逐字匹配；读者还必须核对省略是否丢掉适用条件。这段不能作为合格讲解使用。',
                 '结论：只有在a≠0时，方程ax=1有唯一解x=1/a。',
                 '引用片段在原文中确实按序出现，但省略掉a≠0是不妥的。这里有意展示机械核对的限度：片段逐字相同不证明省略恰当、条件完整或语义忠实。新版记录semantic_verified=false，不把它显示成整篇正确。'),
    ]
    expected = ['not_matched', 'verbatim', 'whitespace_only', 'unresolved', 'unresolved', 'verbatim']
    groups, receipts, table = [], [], []
    for case, status in zip(cases, expected):
        raw = case['text']
        checked = citation_checks(raw, case['records'])
        assert checked['quote_count'] == 1 and checked['quote_results'][0]['status'] == status
        delivered = annotate_chat_quotes(raw, case['records'])
        assert delivered.endswith(raw) and checked['semantic_verified'] is False
        if status in ('verbatim',) or case['id'] == 'own_example':
            assert delivered == raw
        else:
            assert delivered != raw
        durations = []
        for _ in range(21):
            start = perf_counter()
            assert annotate_chat_quotes(raw, case['records']) == delivered
            durations.append((perf_counter() - start) * 1000)
        local_ms = round(median(durations), 3)
        source_bytes = sum(len(part['text']) for rec in case['records'] for part in rec['segments'])
        rows = []
        for arm, label, text in (
            ('raw', '同一回答原文 · 未添加软件提示', raw),
            ('annotated', '同一正文 · 软件核对后的交付', delivered),
        ):
            rows.append({'case': case['id'], 'arm': arm, 'label': label, 'text': text,
                         'review': case['review'], 'seconds': local_ms, 'input_chars': source_bytes,
                         'output_chars': len(text), 'response_model': case['kind'],
                         'usage': {'new_model_requests': 0, 'local_annotation_median_ms': local_ms},
                         'sha256': digest(text), 'request': {'origin': case['origin'], 'checks': checked}})
        groups.append({'round': case['kind'], 'case': case['id'], 'title': case['title'],
                       'question': case['question'], 'source': case['source'], 'rows': rows})
        receipts.append({'case': case['id'], 'kind': case['kind'], 'origin': case['origin'],
                         'source_path': case.get('source_path'), 'source_sha256': case.get('source_sha256'),
                         'raw_sha256': digest(raw), 'delivered_sha256': digest(delivered),
                         'original_body_preserved': delivered.endswith(raw), 'checks': checked,
                         'local_annotation_median_ms': local_ms})
        if case.get('source_path'):
            assert hashlib.sha256((ROOT / case['source_path']).read_bytes()).hexdigest() == case['source_sha256']
        names = {'not_matched': '定位已找到，文字未逐字匹配', 'verbatim': '片段逐字匹配',
                 'whitespace_only': '仅忽略空白匹配', 'unresolved': '无唯一来源定位'}
        result = '保持原样：自己的示意' if case['id'] == 'own_example' else names[status]
        table.append('<tr><td>' + escape(case['title']) + '</td><td>' + escape(result)
                     + '</td><td>' + ('新增本机说明' if delivered != raw else '正文保持原样')
                     + f'</td><td>{local_ms:.3f} ms</td></tr>')

    checks, suites = set(), {}
    for filename in ('quote-provenance-final-regression-20261017.xml',
                     'quote-provenance-context-regression-20261017.xml',
                     'quote-provenance-latest-targeted-20261017.xml'):
        tests = ET.parse(ROOT / 'build' / filename).getroot().findall('.//testcase')
        assert tests and all(t.find(k) is None for t in tests for k in ('failure', 'error', 'skipped'))
        suites[filename] = len(tests)
        checks.update((t.get('classname'), t.get('name')) for t in tests)
    assert len(checks) == 244
    ui_folder = ROOT / 'build/quote-provenance-ui-20261017-1'
    ui = json.loads((ui_folder / 'ui-results.json').read_text(encoding='utf-8'))
    assert ui['passed'] and ui['external_model_requests'] == 0 and len(ui['checks']) == 4
    screenshots = ['成果卡片引文状态.png', '电脑端引文核对.png', '手机端引文核对.png']
    for name in screenshots:
        shutil.copyfile(ui_folder / name, OUT / name)

    intro = '''<header><div class="eyebrow">STUDYFORGE · SOURCE QUOTATIONS · 2026-10-17</div>
<h1>引文要对得上原文，排版相似不等于逐字相同</h1>
<p><a href="../../验收最新版.vbs">打开最新版源码验收</a> · <a href="../../docs/原文引语与转述核对验收.md">详细验收记录</a>。本轮未打包。</p>
<div class="notice">下面是<strong>两份已保存真实回答的回放，以及四份合成边界样例</strong>。每组比较同一正文添加软件提示前后的交付，<strong>不是两次重新生成的AI回答</strong>。没有新增外部模型请求；原回答、来源与指纹保留。逐字片段核对不证明数学等价、引用省略恰当或整篇教学正确。</div></header>'''
    evidence = '''<details class="prompt"><summary>展开查看修复范围、验收证据和仍需改进的地方</summary>
<h2>修复了什么</h2><p>旧统计先删空白再比较，却把结果称为“逐字匹配”。现在分别显示片段逐字匹配、仅忽略空白匹配、文字未匹配和无唯一定位。旧成果没有新字段时标明“未区分空白差异”，不冒充已逐字核对。教材原话后的文件名与行号也在已选来源中核对，不自动打开未选文件。</p>
<p>导师把未匹配文字称为原文时，在回答开头加一段明确标为“软件引文核对”的说明，模型正文原样保留。软件自己的提示随聊天保存、切换、重开和下一轮恢复；普通未署来源的导师示意不一概加提示。原生DeepSeek私有协议可更新时保留；不能原位更新的远端会话下次从公开记录恢复。只添加核对说明，不给学生新增分数或学习判断。</p>
<h2>六组本机回放</h2><div class="report-table"><table><thead><tr><th>样例</th><th>核对结果</th><th>聊天交付</th><th>标注中位耗时</th></tr></thead><tbody>__ROWS__</tbody></table></div>
<p>耗时是同一台电脑上每例21次本机字符串检查的中位值，仅核对与标注，不含模型推理、文件读取、转录、OCR、排版或联网；不作为完整任务提速或总内存结论。原文件内容与回答主体指纹核对不变。完整机器记录保存在本目录“核对记录.json”。</p>
<h2>程序与实际界面验收</h2><p>244项最终相关去重检查通过，包括三份受控完整DOCX生成、真实文件写出与重读，聊天保存和下一轮协议恢复、来源范围、语言及历史记录兼容。四项实际Electron电脑／配对HTTPS手机宽度流程通过：成果卡新旧状态、公式显示、刷新重开、手机继续提问；共两次受控模型响应，零次外部模型请求，未记录私有思考正文。手机是390px浏览器验收，不代替真实安卓手机的全部功能测试。</p>
<h2>仍有边界</h2><p>只处理当前支持的引用块和来源标记，不保证识别所有写法。未逐字匹配可能只是合法改写或公式排版，软件提示核对，不判定数学错误或编造。引用片段按顺序匹配仍可能省掉关键假设，不能自动认证语义忠实。本轮不解决模型重复讲解、全部数学推理或整体长视频速度、总RAM；没有增加默认模型审查轮数。</p>
<p>软件内指南与手机壳v53同步。退出旧源码实例后，可通过上方源码入口验收；已安装EXE的内容不会因本轮源码修改自动改变。</p>
<details><summary>查看实际产品界面截图（隔离测试资料）</summary>
<figure><img src="成果卡片引文状态.png" alt="成果卡逐字、空白与旧记录显示"><figcaption>实际电脑成果卡：逐字与空白分开显示，旧记录兼容验收。</figcaption></figure>
<figure><img src="电脑端引文核对.png" alt="电脑聊天保留原公式并显示软件核对说明"><figcaption>电脑导师：说明与原始正文共同保存，公式正常显示。</figcaption></figure>
<figure><img class="phone-shot" src="手机端引文核对.png" alt="390像素配对HTTPS手机聊天核对说明"><figcaption>配对HTTPS手机宽度：恢复电脑记录并完成下一次受控提问。</figcaption></figure></details></details>'''
    evidence = evidence.replace('__ROWS__', ''.join(table))
    page = re.sub(r'<header>.*?</header>', lambda _: intro, TEMPLATE, flags=re.S).replace('<main>', '<main>' + evidence, 1)
    page = page.replace('<title>StudyForge · 讲解质量真实对照</title>', f'<title>{TITLE} · StudyForge</title>')
    page = page.replace('grid-template-columns:repeat(3,minmax(0,1fr))', 'grid-template-columns:repeat(2,minmax(0,1fr))')
    page = page.replace('</style>', '.report-table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border:1px solid #d2e0d6;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}.lesson-math.display-math{display:block;overflow-x:auto;overflow-y:hidden;padding:6px 0}.katex-display{overflow:visible}figure{margin:20px 0}figure img{display:block;max-width:100%;height:auto;border:1px solid #d8e2df;border-radius:12px}figure .phone-shot{max-width:min(100%,390px)}figcaption{font-size:14px;color:#53656a}</style>', 1)
    css = (ROOT / 'web/vendor/katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,' + base64.b64encode((ROOT / 'web/vendor/fonts' / m[1]).read_bytes()).decode() + ')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    page = page.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', json.dumps({'groups': groups, 'count': 12, 'failures': []}, ensure_ascii=False).replace('<', '\\u003c'))
    page = page.replace('__LIBRARIES__', '\n'.join(inline_script((ROOT / 'web/vendor' / name).read_text(encoding='utf-8')) for name in ('marked.js', 'purify.js', 'katex.js')))
    page = page.replace('__RENDERER__', inline_script((ROOT / 'web/lesson_render.js').read_text(encoding='utf-8')))
    page = page.replace("row.seconds+'秒 · 正文 '+row.output_chars+'字符 · 提示 '+row.input_chars+'字符'", "row.seconds+'毫秒（本机标注） · 交付 '+row.output_chars+'字符 · 核对原文 '+row.input_chars+'字符'")
    page = page.replace("comparison.count+'份原始回答 · '", "comparison.count+'份交付视图 · '")
    page = page.replace('下载这份原始回答（Markdown）', '下载这份交付文本（Markdown）')
    page = page.replace('核对实际请求、用量与原文指纹', '核对历史来源、本机记录与正文指纹')
    page = page.replace('查看本次提供的完整合成原资料', '查看本例实际核对的完整来源')
    page = page.replace('先独立判断：是否回答卡点、关键理由和步骤是否相连、例子与公式是否正确，再查看方案标签。人工评价可质疑，不是经过校准的教学评分。', '核对重点：提示有没有准确区分引用状态、原始回答主体是否保留。可显示方案与人工评价；评价不是经过校准的教学评分。')
    page = page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。', '正文、公式与字体已内嵌；界面截图位于同一文件夹。阅读、切换与下载不发送模型请求。旧回答与反面样例保留用于核对，切勿把它们当作定稿教材。')
    target = OUT / f'{TITLE}.html'
    target.write_text(page, encoding='utf-8')
    (OUT / '核对记录.json').write_text(json.dumps(receipts, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = {'answers': 12, 'groups': 6, 'report_table_rows': [6], 'program_checks': len(checks),
                'suites': suites, 'ui_checks': len(ui['checks']), 'historical_real_answers': 2, 'synthetic_cases': 4,
                'extra_model_requests': 0, 'controlled_ui_responses': 2, 'package_created': False,
                'original_bodies_preserved': True, 'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(target), **manifest}, ensure_ascii=True))


if __name__ == '__main__':
    main()
