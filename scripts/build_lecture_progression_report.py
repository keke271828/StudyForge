"""Offline actual lecture comparison plus replayed format-anchor repair."""
import base64
import copy
import hashlib
from html import escape
import json
from pathlib import Path
import re
import shutil
from xml.etree import ElementTree as ET

from scripts.build_teaching_comparison import TEMPLATE, inline_script

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/lecture-progression-acceptance-20261018'
TITLE = '讲解展开与核查修订实际验收'
NOTES = {
    'constant_product': (
        '关键恒等、数例和逻辑反例都在，1695字符；仍主动展开一次完整求导和重复总结。把保留原题t>0与证明必须正值容易混在一起，不能因此说原规则没有不足。',
        '1754字符，比原版略长且本次更慢，仍加入求导。将“t=1与t=2的对照”称为反驳整个常函数命题的反例容易误导：两点相等本身不能证明函数恒定；同文前面已有一般恒等式，但反例依据应指向该函数族的完整关系。未达成稳定改善。'),
    'rate_units': (
        '各符号、单位和0.03的计算齐全；仍把给定v自行定为正向速率并加入浓度变化时的普遍判断。计量浓度导数关系也补入了原材料没给出的情境，不能认证完整正确。',
        '2981字符，本次较短较快，核心计算保留；但将B大量过量时的近似说成“对B表观零级”，混淆了把B近似固定的伪一级处理与B反应级数。总结又用“只有基元反应”强化必要性，还有浓度必下降等未给定条件，候选未采用。'),
    'limit_proof': (
        '半间距、开邻域、统一门槛和完整证明讲得清楚，3894字符，多次重演同一推导；把N=max写成“必须用最大值”过强，更大的门槛同样可用。',
        '2419字符，本次较短较快，邻域不交条件、正值、同一项的统一门槛均保留，未把半间距写成唯一选择。这份较好样例不抵消化学组的问题，也不证明长书或视频普遍更快。'),
    'social_mechanism': (
        '假设事件、规则影响与替代因素的区别清楚，保留“未排除不等于已证明”。1630字符；解释、比喻、回到原文和总结之间仍有重复。',
        '同样1630字符、本次更慢；同一事件中的多因素更具体，仍区分假设与调查。若干确认和评估步骤有所扩展，不能称为稳定更紧凑。'),
    'requested_extensions': (
        '明确要求的代数、求导和等值线都保留，5151字符；推导重复较多，另加隐函数、正则值等。把(t,1/t)称为“线性参数化”不准确：其第二分量并非线性函数。',
        '保留用户明确要求的三个角度，有限增量交叉项解释有实质价值；6832字符、更长更慢。方向导数记号未说明是否要求单位方向，使用时需交代约定；不能据内容多就认定更好，也不能把充分展开控制硬压成短回答。'),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    folder = ROOT / 'build/lecture-progression-real-20261018-1'
    packet = json.loads((folder / 'inputs.json').read_text(encoding='utf-8'))
    results = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
    assert len(results) == 10 and all(r['status'] == 'completed' and r['model_requests'] == 1 for r in results)
    from studyforge.dialogue_scope import CONTEXT_BOUNDARY
    from studyforge.deepseek_protocol import thinking_parameters
    groups, table, matched = [], [], 0
    for case in packet['cases']:
        baseline, candidate = (case['requests'][arm] for arm in ('baseline', 'candidate'))
        assert baseline[1:] == candidate[1:]
        assert baseline[0]['content'].count(packet['old']) == 1
        assert baseline[0]['content'].replace(packet['old'], packet['new'], 1) == candidate[0]['content']
        arms = {r['arm']: r for r in results if r['case'] == case['id']}
        rows = []
        for number, arm in enumerate(('baseline', 'candidate')):
            row = arms[arm]
            path = folder / row['answer_file']
            raw = path.read_bytes()
            original = raw.decode('utf-8').replace('\r\n', '\n')
            assert hashlib.sha256(original.encode()).hexdigest() == row['answer_sha256']
            messages = copy.deepcopy(case['requests'][arm])
            messages[0]['content'] += CONTEXT_BOUNDARY
            body = {'model': 'deepseek-flash', 'messages': messages, 'stream': True,
                    **thinking_parameters('high'), 'stream_options': {'include_usage': True}}
            assert hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == row['http_attempts'][0]['body_sha256']
            matched += 1
            rows.append({'case': case['id'], 'arm': arm, 'label': '原讲解规则' if arm == 'baseline' else '连续讲解候选（未采用）',
                         'text': raw.decode('utf-8'), 'sha256': hashlib.sha256(raw).hexdigest(),
                         'review': NOTES[case['id']][number], 'seconds': round(row['seconds'], 2),
                         'input_chars': row['input_characters'], 'output_chars': row['characters'],
                         'response_model': row['http_attempts'][0]['returned_model'],
                         'usage': [t['usage'] for t in row['http_attempts']],
                         'request': {'complete_public_messages': case['requests'][arm], 'actual_request_body_sha256': row['http_attempts'][0]['body_sha256'],
                                     'mode': case['mode'], 'style': case['style'], 'level': case['level']}})
        groups.append({'round': '真实文字组件对照 · 候选未采用', 'case': case['id'], 'title': case['title'], 'question': case['question'],
                       'source': case['source'] + '\n\n预定核对点：\n' + '\n'.join(case['checks']), 'rows': rows})
        a, b = arms['baseline'], arms['candidate']
        table.append('<tr><td>' + escape(case['title']) + '</td><td>' + f"{a['seconds']:.2f}秒／{a['characters']}字符" + '</td><td>'
                     + f"{b['seconds']:.2f}秒／{b['characters']}字符" + '</td></tr>')
    assert matched == 10

    replay_dir = ROOT / 'build/review-math-label-replay-20261018-1'
    replay = json.loads((replay_dir / 'results.json').read_text(encoding='utf-8'))
    assert replay['passed'] and replay['new_external_model_requests'] == 0 and replay['total_replayed_responses'] == 2
    row = replay['rows'][0]
    assert row['before_resolved'] == [0] and row['after_resolved'] == [0, 1]
    assert replay['rows'][1]['before_resolved'] == replay['rows'][1]['after_resolved'] == [0, 1]
    old_path, new_path = Path(row['before_file']), replay_dir / row['after_file']
    before, after = old_path.read_bytes(), new_path.read_bytes()
    assert hashlib.sha256(after).hexdigest() == row['after_sha256']
    records = json.loads((ROOT / 'build/supplement-conditions-real-20261017-1/historical_review-baseline-records.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(records[0]['response'].encode()).hexdigest() == row['saved_review_response_sha256']
    groups.append({'round': '已修复 · 相同真实旧核查结果的本机回放', 'case': 'anchor_replay',
        'title': '识别排版差异，让已提出的修订真正写入',
        'question': '原句写A与B，核查锚点写$A$与$B$，原来导致同一问题的一组修订未应用。比较相同原稿和相同保存核查JSON经旧、新定位逻辑得到的交付。',
        'source': replay['source'] + '\n\n原核查要求：\n' + replay['requirements'] + '\n\n匹配修复不证明建议本身正确；本次回放零外部请求，不是另一份模型回答。',
        'rows': [
            {'case': 'anchor_replay', 'arm': 'saved_delivery', 'label': '保存的旧核查交付（历史结果）',
             'text': before.decode('utf-8'), 'sha256': hashlib.sha256(before).hexdigest(),
             'seconds': '历史请求，非本轮耗时', 'input_chars': len(records[0]['system']) + len(records[0]['user']),
             'output_chars': len(before.decode('utf-8')), 'response_model': 'deepseek-flash', 'usage': [],
             'request': {'raw_saved_review': records, 'previously_applied_issue_indices': [0]},
             'review': '同一问题的一处定位因A与$A$的格式差异失败，所以第1项整组没有应用，仍显示待核实。这个保护没有静默漏掉警告，但用户没有得到模型已经提出的完整修订。'},
            {'case': 'anchor_replay', 'arm': 'replayed_delivery', 'label': '修复后本机回放交付（零新增模型请求）',
             'text': after.decode('utf-8'), 'sha256': hashlib.sha256(after).hexdigest(),
             'seconds': '本机回放未单独计时', 'input_chars': 0, 'output_chars': len(after.decode('utf-8')),
             'response_model': '同一保存的核查JSON', 'usage': [], 'request': row,
             'review': '第0、1项修订现都写入，单字母标签格式别名及其原位置／指纹如实记录；没有重新请求核查。另一个已能匹配的旧结果保持不变。原来的实质审查仍为passed=false，修订后没有独立复核，原稿中的其他问题未因此全部消失。'},
        ]})
    for item in row['word_files']:
        shutil.copyfile(replay_dir / item['file'], OUT / item['file'])
    table.append('<tr><td>已修复：旧核查结果回放</td><td>原先应用第0项，保留第1项警告</td><td>现在应用第0、1项；零外部模型请求</td></tr>')
    tests = ET.parse(ROOT / 'build/lecture-review-final-regression-20261018.xml').getroot().findall('.//testcase')
    assert len(tests) == 284 and all(t.find(k) is None for t in tests for k in ('failure', 'error', 'skipped'))

    intro = '''<header><div class="eyebrow">STUDYFORGE · LECTURE PROGRESSION &amp; REVIEW · 2026-10-18</div>
<h1>让核查提出的修订真正进入成果</h1><p>修复公式标签排版造成的定位失败；用10份真实讲解检查连续展开候选，保留其不足。</p>
<p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../docs/讲解展开与核查修订验收.md">详细验收记录</a>。本轮未打包。</p>
<div class="notice"><strong>已经采用的是本机修订定位修复，默认讲解组织规则没有更换。</strong>下方有10份真实DeepSeek文字组件回答和2份旧核查交付视图；旧结果回放没有新增模型请求。本轮10次真实请求均为deepseek-flash／high，模型、资料、模式、风格、详略和提问按组对齐；没有网页端测试。候选两组更快、三组更慢，且仍出现实质问题，未采用。</div></header>'''
    evidence = '''<details class="prompt"><summary>展开查看：采用的修复、拒绝的候选、验证与限制</summary>
<h2>修复已提出却漏写的核查修订</h2><p>原稿里写“A 与 B”，核查返回的原句锚点写“$A$ 与 $B$”，旧逻辑会定位失败。同一问题有多个修订时，只能整组保留警告。本次新增极窄的格式匹配：长中文普通句子里的单个ASCII字母标签，可以识别有无美元定界符；其他文字、空白、数字、公式内容、上下标与导数符号都不归一化。不是数学等价判断或模糊搜索。</p>
<p>仅在唯一普通段落内的完整句子应用，最多8处字母格式别名；代码、标题、列表、表格、原文引用、来源位置、网址、短句、多字母及复杂公式仍须严格定位。精确匹配优先。某处失败或相互冲突时，同一问题整组不应用，继续显示待核实；不会为了写入修订猜测位置。</p>
<p>核查记录新增实际匹配方式、原位置和定位指纹；格式别名不会记录成逐字匹配。应用成功不等于修订观点已经独立验证。没有增加核查轮数或后台模型任务，没有自动修订既有成果；对之后新生成、使用快速核查的成果生效。</p>
<h2>用同一份旧结果验证修复</h2><p>本机回放两份先前保存的真实核查JSON。原来因格式失败的记录从“应用第0项”变为“应用第0、1项”，另一份原本匹配成功的交付保持不变。回放零外部请求，不把回放结果冒充新模型回答。两份报告的原始passed=false均保留，修订后仍注明尚未独立复核。</p>
<p><a href="格式修复前_旧核查交付.docx">格式修复前Word</a> · <a href="格式修复后_核查修订交付.docx">格式修复后Word</a>。两份均含未核实的原讲解与修订判断，只验收替换是否写入，不能当成定稿教材。已重新读取文件结构与公式文字，本轮没有在Microsoft Word中做视觉验收。</p>
<h2>讲解组织候选为什么未采用</h2><p>候选只替换文档组织中的一段：围绕一个问题连续讲清，每段新增解释应推进主线，单一短材料不把同一结论拆成多个角度重复证明。仍保留完整原资料、模式、风格、详略、必要步骤、来源要求、总结与用户要求的充分展开，没有硬设字数上限或裁切输出。</p>
<p>5组共10次真实组件请求中，半间距证明与化学例本次更短更快；单一乘积例仍重复并更慢，社会科学例篇幅相同但更慢，用户明确要求三角度的控制例全部保留却更长。化学候选仍混淆B浓度近似固定与B反应级数，并用“只有基元反应”强化必要性。因此候选没有进入共同教学规则；没有挑选一份较好回答就宣布整体质量提高。</p>
<div class="report-table"><table><thead><tr><th>内容</th><th>原规则／原交付</th><th>候选／修复后</th></tr></thead><tbody>__ROWS__</tbody></table></div>
<p>每组每臂一次，缓存、排队与推理长度影响耗时。10份公开输入和实际HTTP请求指纹逐一吻合；原始回答逐份核对并保留，未保存私有思考正文。耗时为首次文字组件响应，不包含视频下载、OCR、工具调用、核查或Word导出，不能推成整本书或所有成果的提速比例。</p>
<h2>验证与打开</h2><p>284项最终相关程序检查通过，覆盖严格定位与格式别名、引用和来源保护、重复位置与冲突、私有快速核查、原生服务、审查模式、原有数学工具、风格与语言、总结提示和用户指南。早先110项检查与这批重叠，不重复计数。</p>
<p>其中两项完整原生生成流程使用受控模型：分别验证一组修订全部匹配时正文／总结同时写入Word与快照，以及一处无效时整组保留并显示疑点。每项仍只有一次撰写与一次已有快速核查，没有新增题单、分数或模型修复请求。另有上面的两份真实旧响应回放与两个可重读Word文件；受控响应不是云端教学质量证据。</p>
<p>指南和手机页面版本v56同步。关闭旧源码实例后双击顶部“启动最新版源码”使用本次修复；已安装旧EXE不会自动变化。这里只修改了后台修订逻辑和指南，本轮未新增学习工作台交互，也没有宣称全应用RAM、视频速度或所有教学问题已经解决。</p></details>'''
    page = re.sub(r'<header>.*?</header>', lambda _: intro, TEMPLATE, flags=re.S).replace('<main>', '<main>' + evidence.replace('__ROWS__', ''.join(table)), 1)
    page = page.replace('<title>StudyForge · 讲解质量真实对照</title>', f'<title>{TITLE} · StudyForge</title>')
    page = page.replace('grid-template-columns:repeat(3,minmax(0,1fr))', 'grid-template-columns:repeat(2,minmax(0,1fr))')
    page = page.replace('</style>', '.report-table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border:1px solid #d2e0d6;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}.lesson-math.display-math{display:block;overflow-x:auto;overflow-y:hidden;padding:6px 0}.katex-display{overflow:visible}</style>', 1)
    css = (ROOT / 'web/vendor/katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,' + base64.b64encode((ROOT / 'web/vendor/fonts' / m[1]).read_bytes()).decode() + ')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    page = page.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', json.dumps({'groups': groups, 'count': 12, 'failures': []}, ensure_ascii=False).replace('<', '\\u003c'))
    page = page.replace('__LIBRARIES__', '\n'.join(inline_script((ROOT / 'web/vendor' / name).read_text(encoding='utf-8')) for name in ('marked.js', 'purify.js', 'katex.js')))
    page = page.replace('__RENDERER__', inline_script((ROOT / 'web/lesson_render.js').read_text(encoding='utf-8')))
    page = page.replace('份原始回答', '份验收视图').replace('秒 · 正文 ', '秒 · 交付 ')
    page = page.replace("row.seconds+'秒 ·", "row.seconds+(typeof row.seconds==='number'?'秒':'')+' ·")
    page = page.replace('下载这份原始回答', '下载这份交付文本').replace('查看本次提供的完整合成原资料', '查看资料和预定核对范围')
    page = page.replace('核对实际请求、用量与原文指纹', '核对公开输入／核查记录、用量与交付指纹')
    page = page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。', '10份真实组件回答与2份旧核查交付视图原样保留；Word在同一文件夹。查看不请求模型；人工评语可质疑，有缺陷的回答不作定稿教材。')
    target = OUT / (TITLE + '.html')
    target.write_text(page, encoding='utf-8')
    manifest = {'answers': 12, 'groups': 6, 'report_table_rows': [6], 'program_checks': len(tests),
                'real_model_requests': 10, 'replayed_saved_responses': 2, 'replay_new_external_requests': 0,
                'request_fingerprints_matched': matched, 'candidate_policy_adopted': False,
                'package_created': False, 'controlled_native_docx_cases': 2, 'replayed_docx_files': 2,
                'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(target), **manifest}, ensure_ascii=True))


if __name__ == '__main__':
    main()
