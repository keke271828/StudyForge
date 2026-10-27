"""Offline final-answer comparison, with measured limits and no hidden reasoning."""
import base64
import hashlib
from html import escape
import json
from pathlib import Path
import re

from scripts.build_teaching_comparison import TEMPLATE, inline_script

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'build/teaching-data-scope-acceptance-20261026'
GATE = ROOT/'build/teaching-data-scope-final-20261026-1'
ROUND1 = ROOT/'build/followup-quality-20261026-1'
ROUND2 = ROOT/'build/data-scope-quality-20261026-1'
AUDIT = ROOT/'build/data-scope-review-20261026-2'

NOTES = {
    ('followup','epsilon_instance'): [
        '直接说明全称命题可用合法正数特例，区分使用已知收敛与证明收敛。回应当前疑问，没有重做邻域证明；结尾略有回顾。',
        '全称实例化和N随ε改变讲得清楚；但686字符比原版578字符更多，耗时也更长。“任意ε不要求在证明里同时处理所有ε”须结合正在使用收敛假设来理解，不能泛用于证明收敛。未见稳定收益。'],
    ('followup','copy_slot'): [
        '槽位替换与修改原内层区分正确，静态结果保留第二项[2]，没有声称实际运行。本题已经较集中。',
        '更紧凑地说明新[9]只替换b[0]，没有改旧[1]；两份外层列表的静态结果完整。这一例更简洁，不能推成所有追问都改善。'],
    ('followup','causal_mechanisms'): [
        '区分共同原因与反向箭头，也说明原有能力可同时承担混杂角色；保留候选解释尚未验证的限定，没有强制另做研究设计。',
        '两组箭头与可以并存的说明基本对准问题，保留能力的混杂细分；但原文“尚未验证”没有再明确落下，部分措辞读来像已发生机制。未采用为全局替换。'],
    ('followup','full_chemistry'): [
        '单位与0.03计算正确，保留给定模型与反应式的区别；正文5703字符，背景和边界展开偏多。完整要求得到了回应，但没有因此认证整篇无误。',
        '核心单位和数值正确，仍系统展开；多次把资料未说明的给定浓度称为初始浓度。这个条件缺口比字数变短更重要，候选不采用。'],
    ('scope','full_chemistry'): [
        '这一次旧规则已经使用“某一时刻”，主要单位和计算正确；还有不少扩展，以及“v=k”数值解释应始终保留所用单位约定。不能说旧规则每次都会犯初始条件错误。',
        '使用当前/给定时刻而没有擅加初始状态，单位推算、代入与反应式边界保留。仍偏长；恒容条件下的速率等式和后文每秒转化解释，宜持续明确是在补充条件下。这是局部改进，未达无误认证。'],
    ('scope','reading_survey'): [
        '明确20名自愿填写者、昨天、自报，区分样本与全班、单日与长期；假设例子计算完整。个别例子又把自报直接写成“实际读了”，措辞可更严。原版这题已有良好表现。',
        '同样保留对象、时间和自报属性，假设的20/40分钟例子与未知40人造成的全班均值差异完整。不假定偏差方向。正文更短但57.75秒比41.97秒更慢；不能当提速证据。'],
}


def load(path): return json.loads(path.read_text(encoding='utf-8'))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    gate = load(GATE/'command.json')
    assert gate['exit_code'] == 0 and gate['source_frozen']
    assert not any(gate['tests'][k] for k in ('failure','error','skipped'))
    for name, value in gate['production_after'].items(): assert digest(ROOT/name) == value, name
    node_log = (ROOT/'build/teaching-data-scope-node-20261026-1.log').read_text(encoding='utf-8-sig')
    assert re.search(r'# fail 0\b', node_log)
    node_count = int(re.search(r'# tests (\d+)', node_log)[1])
    groups, times = [], []
    for kind, folder, label in [('followup',ROUND1,'追问限制 · 未采用'), ('scope',ROUND2,'数据范围 · 已接入')]:
        packet, results = load(folder/'cases.json'), load(folder/'results.json')
        for case in packet['cases']:
            arms = {r['arm']:r for r in results if r['case']==case['id']}
            rows = []
            for index, arm in enumerate(('baseline','compact')):
                r = arms[arm]
                assert r['status']=='completed' and r['model_requests']==1
                path = folder/r['answer_file']
                assert hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest()==r['answer_sha256']
                requests = case['requests'][arm]
                rows.append({'case':kind+'-'+case['id'], 'arm':arm, 'label':
                    '现有规则' if arm=='baseline' else '新增追问限制 · 未采用' if kind=='followup' else '数据范围规则 · 已接入',
                    'text':path.read_bytes().decode('utf-8'), 'review':NOTES[(kind,case['id'])][index],
                    'seconds':round(r['seconds'],2), 'output_chars':r['output_characters'],
                    'input_chars':sum(len(m['content']) for m in requests), 'response_model':r['model'],
                    'usage':[t['usage'] for t in r['http_attempts']], 'request':requests, 'sha256':digest(path)})
            assert case['requests']['baseline'][1:]==case['requests']['compact'][1:]
            groups.append({'round':label, 'case':case['id'], 'title':case['title'], 'question':case['question'],
                'source':json.dumps({k:case[k] for k in ('source','history','checks','style','mode') if k in case},ensure_ascii=False,indent=2),
                'rows':rows})
            times.append('<tr><td>'+escape(label+' / '+case['title'])+'</td>'+''.join(
                f'<td>{arms[a]["seconds"]:.2f}秒 / {arms[a]["output_characters"]}字符</td>' for a in ('baseline','compact'))+'</tr>')
    audits, audit_cases = load(AUDIT/'results.json'), load(AUDIT/'cases.json')
    for case in audit_cases['cases']:
        rows = []
        for arm in ('baseline','current'):
            r = next(r for r in audits if r['case']==case['id'] and r['arm']==arm)
            assert r['status']=='completed' and r['completion_calls']==r['nonstream_post_invocations']==1
            path = AUDIT/r['document_file']
            assert hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest()==r['document_sha256']
            reports = r['reports']
            if case['id']=='unsupported_initial':
                assert reports[0]['passed'] is False and reports[0]['locally_corrected_issues']==[0]
                assert '这组初始浓度是' not in path.read_text(encoding='utf-8')
                note = '同一次快速核查指出正文与总结共同的无依据初始条件，并用两段局部修正保留数值计算。未另行重写整篇；修正结果没有再做独立复核。新旧规则本次都做到了。'
            else:
                assert reports[0]['passed'] is True and not reports[0]['issues']
                assert path.read_text(encoding='utf-8')==case['document']
                note = '把假设与资料分清后，审查没有因出现“初始”字样而判错；整个示例原样保留。新旧规则本次都通过。'
            requests = load(AUDIT/(case['id']+'-'+arm+'-requests.json'))
            rows.append({'case':case['id'], 'arm':arm, 'label':'原有快速审查' if arm=='baseline' else '加入数据范围规则的快速审查',
                'text':path.read_bytes().decode('utf-8'), 'review':note, 'seconds':round(r['seconds'],2),
                'output_chars':len(path.read_text(encoding='utf-8')), 'input_chars':sum(len(v) for v in requests[0].values()),
                'response_model':r['response_receipts'][0]['returned_model'],
                'usage':[receipt['usage'] for receipt in r['response_receipts']],
                'request':{'messages':requests,'audit_reports':reports,'transport_retry_count':None}, 'sha256':digest(path)})
        groups.append({'round':'真实快速审查', 'case':case['id'], 'title':'擅加初始条件' if case['id']=='unsupported_initial' else '允许明确的补充假设',
            'question':audit_cases['requirements'], 'source':audit_cases['source']+'\n\n【待审原稿】\n'+case['document'], 'rows':rows})
    rows_count = sum(len(g['rows']) for g in groups)
    assert rows_count==16
    header = '''<header><div class="eyebrow">STUDYFORGE · 2026-10-26</div><h1>讲解可以展开，给定条件不能悄悄改变</h1><p>数学与编程追问、社会科学解释、完整化学讲解，以及实际快速审查。</p><div class="notice">这轮没有采用“再加一条限制就会整体更好”的方案。采用的改动只有一条共同原则：保留数据的时间、状态与样本范围；额外条件先声明为假设。报告同时保留旧规则表现好的回答和新规则的不足。</div></header>'''
    evidence = f'''<section class="prompt"><h2>已经交付什么</h2><p>导师和文档撰写使用同一条数据范围规则，已有审查同步核对。未增加固定审查轮次。极速仍无独立审查，快速仍一次核查；明确的假设例子可以保留。旧公开聊天不清空，下一次请求更新模型私有状态。</p><p><a href="../../验收最新版.vbs">打开最新版源码</a>：先退出托盘旧版，再双击。<strong>本轮未打包</strong>，原0.4.5安装器与源码ZIP保留发布时的快照。<a href="../../docs/教学条件保留与真实对照-20261026.md">修改与验收说明</a>。</p></section>
<details class="prompt"><summary>实验方法、时间与不足（先看这一段，再判断哪版更好）</summary><p>前两轮共12份实际DeepSeek最终回答：接口返回模型为deepseek-flash，推理high，工具与联网关闭，最多2个模型调用同时进行。输入捕获自真实导师／文档构造路径，两臂除共同规则外其余消息相同。每种问题每臂1次，结果不证明通用优胜；请求前后缓存和服务负载并不相同。文档对照只测撰写阶段，不含独立审查和Word排版，不能当完整任务时间。</p><table><thead><tr><th>实验 / 问题</th><th>原有规则</th><th>候选规则</th></tr></thead><tbody>{''.join(times)}</tbody></table><p>只补卡点的候选被放弃：数学更长更慢；化学擅加初始条件。数据范围候选使用给定时刻，社会调查仍保留时间、对象与自报属性，但后者41.97→57.75秒，不能宣称稳定提速。长化学讲解仍有扩展偏多、后续条件宜反复交代的问题，不认证为完美教材。</p><p>另做2轮共8次真实快速审查；下方展示计数补全后的4次。首次4次使用的流式计时器未覆盖非流式审查，不能把当时的0计数理解为0请求；<a href="../data-scope-review-20261026-1/results.json">首次结果保留</a>。复测每次各1个完成调用、1个非流式POST调用；内部连接重试次数没有单独记录。两轮新旧规则均修正不支持的初始条件、保留明确的假设例子。不是网页端、其他模型、真实长视频或整本扫描书对照。</p><p>下方显示的是首次最终正文或快速审查实际修正后的正文，未人为润色。审查原始JSON在对应的“实际请求”内；不展示隐藏推理内容。样例均为合成资料，没有发送你的真实聊天或书籍。</p></details>
<section class="prompt"><h2>软件交付回归</h2><p><strong>{gate['tests']['total']}项Python回归、{node_count}项前端测试通过。</strong>新增完整Word任务在实际软件流程中用受控HTTP回复验证：1次撰写＋1次快速审查，修正内容进入最终DOCX；原文引用、计算和假设例子保留，只交付要求的讲解文件，没有同步题单。受控回复验证传递，真实DeepSeek输出验证样例内容，两类证据分开。</p><p>Word重新读取了内容，本轮未重新检验Word外观、安卓实机、完整长视频和整机内存。没有修改真实数据库或默认模型。<a href="../{GATE.name}/command.json">回归与源码指纹</a> · <a href="../teaching-data-scope-node-20261026-1.log">前端日志</a> · <a href="../{AUDIT.name}/results.json">计数与实际审查结果</a></p></section>'''
    page = re.sub(r'<header>.*?</header>', lambda m:header, TEMPLATE, flags=re.S).replace('<main>','<main>'+evidence,1)
    page = page.replace('<title>StudyForge · 讲解质量真实对照</title>','<title>教学条件保留与真实讲解对照 · StudyForge</title>')
    page = page.replace('repeat(3,minmax(0,1fr))','repeat(2,minmax(0,1fr))')
    page = page.replace('</style>','table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border:1px solid #d8e2df;text-align:left}a{color:#236b5b}.prompt{overflow-wrap:anywhere;overflow-x:auto}.lesson-math.display-math{display:block;overflow-x:auto;overflow-y:hidden;padding:8px 0}.katex-display{overflow:visible}</style>',1)
    css = (ROOT/'web/vendor/katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((ROOT/'web/vendor/fonts'/m[1]).read_bytes()).decode()+')',css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
    page = page.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',json.dumps({'groups':groups,'count':rows_count,'failures':[]},ensure_ascii=False).replace('<','\\u003c'))
    page = page.replace('__LIBRARIES__','\n'.join(inline_script((ROOT/'web/vendor'/name).read_text(encoding='utf-8')) for name in ('marked.js','purify.js','katex.js')))
    page = page.replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    page = page.replace('查看本次提供的完整合成原资料','查看合成原资料、已有对话或待审原稿')
    OUT.mkdir(exist_ok=True)
    target=OUT/'教学条件保留与真实讲解对照.html'
    target.write_text(page,encoding='utf-8')
    manifest={'python':gate,'node_tests':node_count,'shown_outputs':rows_count,'author_answers':12,
        'real_audits':8,'earlier_audit_counter_incomplete':True,'displayed_audits':4,
        'followup_candidate_adopted':False,'data_scope_adopted':True,'packaged':False,
        'report_sha256':digest(target)}
    (OUT/'verification.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(target)


if __name__=='__main__':main()
