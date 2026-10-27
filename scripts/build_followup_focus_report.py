"""Package the rejected prompt experiment and accepted input fix, offline."""
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
PROBE = ROOT / 'build/followup-focus-real-20261016-1'
UI = ROOT / 'build/followup-focus-ui-20261016-1'
OUT = ROOT / 'build/followup-focus-acceptance-20261016'
NOTES = {
    'epsilon_instance': [
        '抓住了全称命题可以使用合法正数特例，且先核对a<b。但1338字符中存在性比较和收束偏多；“存在量词没有选择权”缺少“仅由存在性信息不能指定某个任意值”的限定，关于a、b尚未固定就必为误用的说法也过宽。',
        '开头说明全称例示正确，但又重讲已懂的邻域和矛盾。后面说“只检验了一个ε不成立，就否定极限……确实不够”，表述有实质问题：若某个正ε使任何N都不能保证其后的项满足要求，已经可以否定该单一极限；只发现一个有限项不满足则不能。这与本题的两个极限联合假设还需区分。未采用。'],
    'copy_slot': [
        '269字符准确解释只替换b的槽位，没有改旧内层；完整静态结果a=[[1],[2]]、b=[[9],[2]]正确，未扩写append课程。',
        '核心槽位解释正确，但静态结果写成a=[[1]]、b=[[9]]，把未改动的第二项[2]都漏掉了；还有额外抽屉类比，正文反而更长。独立本机运行固定三行代码确认两列表都应保留第二项。不能以耗时略短抵消结果错误。'],
    'feedback_endpoint': [
        '正确说明有界不等于趋近0，并用任意小的邻近初值δ解释，因此未把不渐近稳定说成必趋无穷。但后半增加不必要的双轨道说明，末尾“不稳定”措辞容易混淆通常稳定性与渐近稳定；这里应始终明确后者。',
        '距离恒为1、扰动不衰减的计算正确；却加了1+ε附近双轨道，没有直接用任意接近0的初值说明局部性质。其首句双轨道距离条件并非本题要用的定义，且726字符比原版长，没有体现只补卡点的稳定收益。'],
    'causal_mechanisms': [
        '两种箭头与可以并存的解释清楚；还保留了“理解快若同时影响两侧也可作为混杂”的必要细分。案例是假想候选，不能据此证明真实机制。没有另设计实验。',
        '424字符更紧凑，保留共同原因、反向箭头和候选尚未验证，但把理解快与已有高分合写，少了原版对这两者可能承担不同角色的辨别。此题可用，不足以支持全局换规则。'],
    'instant_derivative': [
        '区分一个时刻与全区间、核对E′=2αt、必要条件和中值定理均对准问题；含0且有非零长度的区间条件明确。一阶展开和最后再证明略多，没有另推运动方程。',
        '704字符更集中，给定示意和必要／充分区分正确；只是在“邻域内增加”处宜明确非零时刻的值高于E(0)，避免误读为穿过0全程单调增加。两版都没有把示意当真实装置。'],
    'full_chemistry': [
        '单位推导和0.03 mol/(L·s)正确，区分给定模型与反应式，末尾有总结。但3578字符包含未要求的零级、一级、非理想与传质等背景；这些内容应与材料本身区分，“k通常并非常数”也需结合固定实验条件限定。保留不足，不认证整篇无误。',
        '主要数值和单位正确，却扩至5164字符、64.01秒。给定浓度被自行称为“初始浓度”；按摩尔数的计量比例也被额外绑定恒容；“基元反应才可以”的必要性措辞与后面的经验速率律说明不一致。还添加多种未标明补充身份的机理背景。未能同时改善范围、质量和效率。'],
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    packet, results = load(PROBE / 'cases.json'), load(PROBE / 'results.json')
    ui = load(UI / 'ui-results.json')
    benchmark_path = ROOT / 'build/reference-input-benchmark-20261016/引用输入本机比较.json'
    benchmark = load(benchmark_path)
    assert len(results) == 12 and all(r['status'] == 'completed' and r['model_requests'] == 1 for r in results)
    assert ui['passed'] and len(ui['checks']) == 5 and ui['external_model_requests'] == 0
    assert benchmark['model_requests'] == 0 and benchmark['legacy_matches_saved_real_inputs'] == 3
    groups, times = [], []
    for case in packet['cases']:
        by_arm = {r['arm']: r for r in results if r['case'] == case['id']}
        rows = []
        for index, (arm, label) in enumerate((('baseline', '现有共同规则'), ('compact', '新增只补卡点规则 · 未采用'))):
            row = by_arm[arm]
            path = PROBE / row['answer_file']
            answer = path.read_bytes().decode('utf-8')
            # Sampling hashes the returned text; Windows write_text adds CRLF.
            # Verify that original text, but preserve the saved/downloaded bytes.
            normalized = path.read_text(encoding='utf-8')
            assert hashlib.sha256(normalized.encode()).hexdigest() == row['answer_sha256']
            assert len(normalized) == row['output_characters']
            rows.append({
                'case': case['id'], 'arm': arm, 'label': label, 'text': answer,
                'review': NOTES[case['id']][index], 'seconds': round(row['seconds'], 2),
                'input_chars': sum(len(m['content']) for m in case['requests'][arm]),
                'output_chars': row['output_characters'], 'response_model': row['model'],
                'usage': [t['usage'] for t in row['http_attempts']],
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'request': case['requests'][arm],
            })
        a, b = by_arm['baseline'], by_arm['compact']
        times.append('<tr><td>' + escape(case['title']) + '</td><td>'
                     + f"{a['seconds']:.2f}秒／{a['output_characters']}字符" + '</td><td>'
                     + f"{b['seconds']:.2f}秒／{b['output_characters']}字符" + '</td></tr>')
        source = case['source'] + '\n\n此前公开AI回答：\n' + '\n'.join(m['content'] for m in case.get('history', []))
        source += '\n\n采样前固定核对点：\n' + '\n'.join(case['checks'])
        groups.append({
            'round': ('开发例' if case['phase'] == 'development' else '预留例') + ' · '
                     + ('导师入口' if case['role'] == 'tutor' else '讲解输入'),
            'case': case['id'], 'title': case['title'], 'question': case['question'],
            'source': source, 'rows': rows,
        })
    checks, suites = set(), {}
    for name in ('followup-focus-final-regression-20261016.xml', 'followup-focus-delivery-regression-20261016.xml',
                 'followup-focus-guide-final-20261016.xml'):
        rows = ET.parse(ROOT / 'build' / name).getroot().findall('.//testcase')
        assert rows and all(r.find(k) is None for r in rows for k in ('failure', 'error', 'skipped'))
        suites[name] = len(rows)
        checks.update((r.get('classname'), r.get('name')) for r in rows)
    reductions = ''.join('<tr><td>{selected_characters}</td><td>{legacy_characters}</td>'
                         '<td>{new_characters}</td><td>{input_reduction_percent:+.2f}%</td></tr>'.format(**r)
                         for r in benchmark['results'])
    for name in ('电脑端原句追问.png', '手机端原句选择.png', '手机端原句追问.png'):
        shutil.copyfile(UI / name, OUT / name)
    shutil.copyfile(benchmark_path, OUT / benchmark_path.name)
    intro = '''<header><div class="eyebrow">STUDYFORGE · FOLLOW-UP INPUT · 2026-10-16</div>
<h1>把追问对准卡点，也检查“精简规则”会不会伤害教学</h1>
<p>6组12份真实回答，原样保留错误与不足。<a href="../../验收最新版.vbs">源码验收入口</a> · <a href="../../docs/追问聚焦与引用输入优化验收.md">验收记录</a>。本轮未打包。</p>
<div class="notice"><strong>候选提示词未采用。</strong>它在5题更快，却把编程示例未改动的第二项漏掉，完整讲解也更长更慢。实际落地的是引用输入去重与旧内部上下文的版本更新；不把这两种不同的改动混作同一次质量提升证明。</div></header>'''
    evidence = '''<details class="prompt" open><summary>实际改动、实验结论与验收</summary>
<h2>已经落实：同一选段在上下文中只发送一份</h2>
<p>旧输入既单独放选中原句，又把包含它的附近上下文发送一次。现在在原上下文中直接标明开始／结束，坐标、原句、邻近文字和内容指纹均保留。移除定位标记可按原顺序还原同一份上下文；原句可能跨公式或代码边界，这一点也在输入中说明。保存的学生问题、原始AI回答与引用记录不截短，不改变学生原话。</p>
<p>这是针对引用包装的精简。完整来源仍由原文读取流程提供；对话原本就出现过的句子、或不同真实位置的重复句，不会被全局去重。已有引用的对话按新版输入标记从公开历史重建内部上下文，再正常续接；无引用对话不因这个版本重建。旧隐藏协议不被继续复用，原公开消息保持。</p>
<div class="report-table"><table><thead><tr><th>选段字符</th><th>旧引用输入字符</th><th>新引用输入字符</th><th>减少比例</th></tr></thead><tbody>__REDUCTIONS__</tbody></table></div>
<p>正号表示减少，负号表示增加。40字符短选段增加51字符定位说明；1000字符选段减少909字符，3000字符减少2909字符。前后均逐字还原原上下文，保存的引用未变。先用上轮3份实际输入核对旧格式，再做本地31次构造；新构造中位约0.005—0.007毫秒。此处测的是<strong>引用包装字符</strong>，不是完整任务token、云端等待、总内存或视频速度。<a href="引用输入本机比较.json">原始本机记录</a>。</p>
<h2>本次真实模型试验：不采用一条看似合理的额外规则</h2>
<p>DeepSeek Flash／high；工具与联网关闭。5组使用实际导师输入捕获，1组使用实际文档输入构造；2个开发例、4个预留例均在采样前固定，没有按答案继续调规则。每臂各1次，分别保留完整首次正文与公开请求，没有盲评、重复抽样、网页端或其他模型对照，也不包含额外审核与排版耗时。正文字符按模型返回统计；下载保留所存文件的Windows换行，文件指纹与下载文字一致。</p>
<p>候选只额外增加73字符：“学生明确说已懂某部分或只追问一步时，把篇幅用于剩下的卡点；只回顾接通它所必需的内容，不重复完整证明、平行解法或再总结。学生要求全面展开时充分展开。”两臂其余规则、材料、问题、学习模式与风格一致。<strong>共同生产规则仍为2026-10-16-preserve-valid-reasoning。</strong></p>
<div class="report-table"><table><thead><tr><th>问题</th><th>现有规则</th><th>候选规则 · 未采用</th></tr></thead><tbody>__TIMES__</tbody></table></div>
<p>候选5组更快、1组更慢；3组更短、3组更长。完整化学讲解从38.74秒／3578字符升到64.01秒／5164字符，还添加了资料未给的“初始浓度”。编程候选把a、b都写成只有一个元素，独立本机固定代码运行确认第二项[2]仍应保留。数学候选还把“一个ε的最终性条件失败可否否定极限”解释混乱。现有规则也有重复和边界措辞不足，下方逐题保留评价，不标记全部优秀。</p>
<h2>完整交付与两端检查</h2>
<p>__CHECKS__项最终相关去重程序检查通过。新增完整DOCX任务用实际DeepSeek客户端和受控HTTP响应运行：选中原句在对应历史引用条目中只出现一次，附近上下文和所选原文首、中、尾均存在；任务启动后的新聊天不混入；实际写出Word后重新读取正文，原学生问题与冻结任务输入保持，不新增题单或画像分数。该项1次受控请求验证传递与交付，<strong>不是云端教学质量样本</strong>。</p>
<p>另5项实际Electron电脑／配对HTTPS手机宽度交互通过：长回答后段与Unicode／CRLF原句、按对话恢复草稿、发送并重开历史、手机短回答引用、不因引用产生掌握分或画像判断。2次受控请求，0次外部请求，控制台无错误；没有重新测试真实安卓设备。软件内指南与手机壳v51同步。</p>
<details><summary>查看实际界面截图</summary><p><img src="电脑端原句追问.png" alt="电脑端针对具体原句追问" style="max-width:100%"></p><p><img src="手机端原句选择.png" alt="手机宽度选择原句" style="width:100%;max-width:390px"></p><p><img src="手机端原句追问.png" alt="手机宽度追问历史" style="width:100%;max-width:390px"></p></details>
<p>打开最新源码：完全退出旧源码版后，双击<a href="../../验收最新版.vbs">验收最新版</a>。在已完成回答下点击“针对这段追问”，选原句，再用原输入框提问。安装包没有被本轮源码修改替换。实验使用隔离资料和设置；未改动真实资料、画像或模型选择。</p>
<p>本轮没有证明整软件内存下降、扫描书或长视频更快，也没有解决所有教学冗长。减少重复输入是已实现的确定改动；模型是否把剩余卡点讲好，仍须看具体回答。</p></details>'''
    evidence = evidence.replace('__REDUCTIONS__', reductions).replace('__TIMES__', ''.join(times)).replace('__CHECKS__', str(len(checks)))
    page = re.sub(r'<header>.*?</header>', lambda _: intro, TEMPLATE, flags=re.S).replace('<main>', '<main>' + evidence, 1)
    page = page.replace('<title>StudyForge · 讲解质量真实对照</title>', '<title>追问范围与引用输入实际对照 · StudyForge</title>')
    page = page.replace('grid-template-columns:repeat(3,minmax(0,1fr))', 'grid-template-columns:repeat(2,minmax(0,1fr))')
    page = page.replace('</style>', '.report-table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border:1px solid #d2e0d6;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}.lesson-math.display-math{display:block;overflow-x:auto;overflow-y:hidden;padding:6px 0}.katex-display{overflow:visible}</style>', 1)
    css = (ROOT / 'web/vendor/katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,' + base64.b64encode((ROOT / 'web/vendor/fonts' / m[1]).read_bytes()).decode() + ')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    page = page.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', json.dumps({'groups': groups, 'count': 12, 'failures': []}, ensure_ascii=False).replace('<', '\\u003c'))
    page = page.replace('__LIBRARIES__', '\n'.join(inline_script((ROOT / 'web/vendor' / name).read_text(encoding='utf-8')) for name in ('marked.js', 'purify.js', 'katex.js')))
    page = page.replace('__RENDERER__', inline_script((ROOT / 'web/lesson_render.js').read_text(encoding='utf-8')))
    page = page.replace('查看本次提供的完整合成原资料', '查看合成原资料、此前回答和采样前核对点')
    page = page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。', '完整原始正文、公开请求、公式渲染和字体均内嵌；阅读与下载不请求模型。两版均有不足，候选规则未采用，请勿将实验输出当定稿教材。')
    target = OUT / '追问范围与引用输入实际对照.html'
    target.write_text(page, encoding='utf-8')
    manifest = {
        'answers': 12, 'groups': 6, 'report_table_rows': [3, 6], 'program_checks': len(checks), 'suites': suites,
        'ui_checks': 5, 'real_model_requests': 12, 'candidate_adopted': False,
        'reference_input_version': 'message-reference-v2-single-passage',
        'package_created': False, 'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(target), 'checks': len(checks), 'real_model_requests': 12, 'candidate_adopted': False}, ensure_ascii=True))


if __name__ == '__main__':
    main()
