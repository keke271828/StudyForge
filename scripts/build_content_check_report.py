"""Self-contained acceptance report with rejected candidates and original finals."""
import hashlib
from html import escape as esc
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/content-check-review-20261015'
TRIALS=[('第一轮：原句优先索引','review-focus-eval-20261015-1','focus'),
        ('第二轮：实际前提与逐项回执','review-focus-v2-eval-20261015-1','candidate')]
NAMES={'delivered_default':'既有长讲解 A（原前提解释存在歧义）','delivered_high':'既有长讲解 B（含过强断言）',
       'correct_math_control':'数学对照（弱／强前提边界未明确）','flawed_causal_holdout':'统计证据错误样例',
       'correct_social_control':'正确社会科学对照','weak_wrong':'仅有闭区间前提：错误讲解',
       'weak_correct':'仅有闭区间前提：正确讲解','strong_correct':'严格前提仍保留：正确讲解',
       'construction_correct':'方便构造并非唯一：正确讲解'}
NOTES={
 ('focus','delivered_default'):'两臂都未可靠处理初定的边界问题；候选转而质疑软件的来源提示。核对来源编号时需沿用实际解析器规则，不能自行重新编号。原边界问题的强弱前提也需进一步澄清。',
 ('focus','delivered_high'):'基线判通过；候选发现“别无选择”的过强断言并局部修正，仍未指出另外两处半径／中点断言。候选还反对明确标作演示的假定数字；该意见不直接算作已确认数学错误。',
 ('focus','correct_math_control'):'原先标作正确对照，但“闭区间时不能用严格估计”没有明确是否撤销原收敛定义的严格前提。候选异议有可讨论依据，因此不把本例计入干净的误报率；原标签保留在原始记录。',
 ('focus','flawed_causal_holdout'):'两臂均指出显著性不等于大效应、正平均效应不保证所有人受益，并修正正文与总结的对应句。',
 ('focus','correct_social_control'):'两臂均通过；明确标明的假设例子没有被判为捏造事实。',
 ('candidate','delivered_high'):'候选将全部优先核对项标为支持，仍通过含“别无选择”和半径／中点过强断言的讲解；逐项回执并没有保证判断可靠。基线这次指出“别无选择”，与上一轮基线存在抽样波动。',
 ('candidate','weak_wrong'):'两臂均定位闭区间被错误加强为严格内点，并对正文与总结给出对应修正。',
 ('candidate','weak_correct'):'候选因附加审核说明而判不通过；该说明被接在“待审讲解”后，出现指令与被审内容的边界混淆。此结果不能直接算模型对正确数学的误报，也不能算干净的准确率对照。该候选实现未采用。',
 ('candidate','strong_correct'):'两臂均通过，允许使用本段明确保留的严格前提。',
 ('candidate','construction_correct'):'两臂均通过，区分同时越过两门槛的目标、最小门槛与其他可行构造。',
}


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def pre(text):return '<pre>'+esc(text)+'</pre>'
def details(title,body):return '<details><summary>'+esc(title)+'</summary>'+body+'</details>'


def main():
    OUT.mkdir(exist_ok=True)
    ui=ROOT/'build/lesson-content-check-ui-20261015-2';ui_report=load(ui/'ui-report.json')
    assert ui_report['passed'] and len(ui_report['checks'])==5 and not ui_report['console_errors']
    real=load(ROOT/'build/content-check-real-20261015-1/results.json')
    assert len(real)==2 and all(x['status']=='completed' and x['model_requests']==1 for x in real)
    cases_by_id={};regression_files=['lesson-content-check-final-regression-20261015.xml','lesson-content-check-regression-recheck-20261015.xml']
    for file in regression_files:
        for case in ET.parse(ROOT/'build'/file).getroot().findall('.//testcase'):
            cases_by_id[(case.get('classname'),case.get('name'))]=case
    cases=list(cases_by_id.values())
    assert cases and not any(any(c.find(tag) is not None for tag in ('failure','error','skipped')) for c in cases)
    for name in ('desktop-content-check.png','phone-mixed-content-check.png'):shutil.copyfile(ui/name,OUT/name)
    sections=[];request_count=0;tables=[]
    for title,folder,arm in TRIALS:
        base=ROOT/'build'/folder;inputs=load(base/'inputs.json');results=load(base/'results.json')
        assert len(results)==10 and all(x['status']=='completed' and x['model_requests']==1 for x in results)
        request_count+=sum(x['model_requests'] for x in results);rows=[];body=[]
        for case in inputs:
            pair={x['arm']:x for x in results if x['case']==case['id']};a=pair['baseline'];b=pair[arm]
            verdict=lambda x:'判通过' if x['reports'][0]['passed'] else '提出问题'
            rows.append('<tr><td>'+esc(NAMES[case['id']])+'</td>'+''.join('<td>'+verdict(x)+'<br>'+f"{x['seconds']:.2f} 秒"+'</td>' for x in (a,b))+'</tr>')
            cells=[]
            for label,x in [('现有核查',a),('候选核查',b)]:
                final=load(base/x['records_file'])[-1]['response']
                cells.append('<div><h4>'+label+'</h4>'+details('查看最终审核回答（不含模型思考）',pre(final))+
                    details('查看应用局部修正后的讲解',pre((base/x['final_document_file']).read_text(encoding='utf-8')))+'</div>')
            body.append('<article><h3>'+esc(NAMES[case['id']])+'</h3><p class="note">'+esc(NOTES[(arm,case['id'])])+'</p>'+
                details('查看本例原资料、要求与待审讲解',pre('原资料：\n'+case['source']+'\n\n本次要求：\n'+case['requirements']+'\n\n待审讲解：\n'+case['document']))+
                '<div class="pair">'+''.join(cells)+'</div></article>')
        table='<div class="table-wrap"><table><thead><tr><th>样例</th><th>现有核查</th><th>候选核查</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
        tables.append(5);sections.append('<section><span class="kicker">保留完整结果 · 候选未采用</span><h2>'+title+'</h2>'+table+''.join(body)+'</section>')
    assert request_count==20
    real_blocks=[]
    reviews=[
        '正确更正了“闭区间推出严格小于”的错误，指出 x=1 是反例，给出非严格结论和得到严格结论所需的额外条件。回答有重复，短例通过不代表长文可靠性已解决。',
        '没有附和错误质疑；区分闭区间集合包含端点与变量仍受严格前提约束，并用条件交集解释。回答较长、末尾没有再问一句是否理解；不据此宣称教学表达已经最优。',
    ]
    for row,note in zip(real,reviews):
        label='旧讲解确有错误' if row['id']=='correct_real_error' else '学生质疑不成立'
        real_blocks.append('<article><h3>'+label+f" · {row['seconds']:.2f} 秒</h3><p>人工评阅："+note+'</p>'+
            details('查看给定资料、旧讲解与学生反馈',pre(json.dumps(row['inputs'],ensure_ascii=False,indent=2)))+
            details('查看真实模型最终回答',pre(row['answer']))+'</article>')
    for name in ('UI检验记录.json','真实模型短例记录.json'):
        (OUT/name).write_text(json.dumps(ui_report if name.startswith('UI') else real,ensure_ascii=False,indent=2),encoding='utf-8')
    style='''*{box-sizing:border-box}body{margin:0;background:#edf1ed;color:#1d332d;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1190px;margin:auto;padding:40px 22px 70px}header,section{background:#fffdf8;border:1px solid #d8e0d9;border-radius:22px;padding:30px;margin:0 0 24px}h1{font-size:32px;line-height:1.4;margin:10px 0}h2{margin:8px 0 20px;line-height:1.45}h3{font-size:19px}h4{margin:10px 0}.kicker{font-size:13px;letter-spacing:.08em;font-weight:700;color:#286550}.note{background:#f1f5f0;padding:16px;border-left:4px solid #50826b;border-radius:8px}.warn{background:#fff3d8;border-left-color:#b98536}.grid,.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.grid>*,.pair>*,details{min-width:0}p,li,a,summary,td,th{overflow-wrap:anywhere}.metric{padding:15px;background:#edf4ed;border-radius:13px}.metric strong{display:block;font-size:26px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:13px 12px;border-bottom:1px solid #dce3dc;text-align:left;vertical-align:top}th{background:#eef4ee}article{padding:20px 0;border-bottom:1px solid #dce3dc}details{background:#f6f7f3;border:1px solid #dce3dc;border-radius:12px;padding:11px 14px;margin:12px 0}summary{cursor:pointer;font-weight:600}pre{font:14px/1.8 Consolas,"Microsoft YaHei",monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:680px;overflow:auto}a{color:#21634d}figure{margin:16px 0}img{max-width:100%;height:auto;border:1px solid #cbd7ce;border-radius:13px}.phone{width:100%;max-width:390px}small{color:#51665b}li{margin:7px 0}@media(max-width:700px){main{padding:14px 10px}header,section{padding:20px 16px;border-radius:17px}h1{font-size:25px}.grid,.pair{grid-template-columns:minmax(0,1fr)}td,th{padding:9px 7px}}'''
    head='''<header><span class="kicker">STUDYFORGE · 学习质量验收 · 2026-10-15</span><h1>先核对讲解，再定位理解困难</h1><p>本轮增加内容核对反馈，保留六类学习困难；同时完成两组审核候选对照。原始失败、前提歧义和实现边界混淆均保留，候选没有进入正式生成流程。</p><div class="grid"><div class="metric"><strong>20 次</strong>审核对照请求，候选未采用</div><div class="metric"><strong>2 次</strong>真实导师短例，均完成</div><div class="metric"><strong>TEST_COUNT 项</strong>最终回归检查，去重统计</div><div class="metric"><strong>5 项</strong>真实电脑／配对 HTTPS 手机交互</div></div></header>'''.replace('TEST_COUNT',str(len(cases)))
    feature='''<section><span class="kicker">已进入源码</span><h2>新增“讲解可能有误或依据不清，请先核对”</h2><ol><li>生成讲解后打开理解反馈，可选择新增的内容核对项，也可保留原有六类理解困难，多选或填写补充。</li><li>可定位章节和具体原句，说明有疑问的条件、页码或反例。保存时不调用模型；主动请求导师回应才进入原有补讲流程。</li><li>导师使用这份讲解所属的原项目、原对话、原资料与原讲解配置。先判断质疑是否成立，再更正或解释，不假定旧讲解或学生一定正确。</li><li>纯内容质疑不建立学习事件或薄弱项，不改变分数；混合选择仅保留明确勾选的学习困难为未验证自报，质疑补充文字不进入画像。</li><li>不自动生成新习题，也不据此声称已经掌握。可继续使用原有自愿单题理解检查。</li></ol><p class="note">本轮只增加按需核对的入口与上下文规则，没有给每次讲解再加一轮审核、没有降低所选模型或推理强度。历史画像不作追溯删除。单凭提示词仍无法保证任意内容无误。</p></section>'''
    limitations='''<section><h2>怎样理解这次对照</h2><p>两轮均使用实际 DeepSeek 接口的 deepseek-flash、high；每轮五例、每例基线和候选各一次请求。每对可在两个名额内重叠，配对间依次进行。保留完整原文与讲解，并保存最终审核回答、用量与计时，不保存模型思考文本。</p><p>这是审核组件试验，不包含完整 Agent 工具、联网或真实学生上下文；只有少量数学与统计样例，没有重复抽样、盲评或大规模多模型覆盖。时间包含服务波动和共享并发，不能当作普遍速度排名。</p><p class="note warn">第一轮数学对照存在未明确的强弱前提，第二轮有附加说明与被审正文的边界混淆，均不能拿来计算干净的误报率。后者首先是候选接入方式的缺陷。即便不计这些例子，长文过强断言仍有漏检；现有审核也会漏检，因此不能把“审核通过”显示成准确性保证。</p><p>后续有价值的方向是提高资料与待审正文的边界、使用独立且前提明确的短测试，并保留可定位的反馈；继续堆叠长提示和强制回执的方案，本轮没有获得支持。</p></section>'''
    acceptance='<section><h2>两端实际操作</h2><p>隔离的本地后端、真实 Electron 桌面界面与配对 HTTPS 手机页面；模型响应受控，验证按钮、保存、持久化、范围与画像隔离，共2次受控导师请求、0次外部模型请求。不是在安卓实机上完成的测试。</p><p>程序回归初轮149项通过、1项旧测试替身未接收现有推理强度参数；更新替身签名后，该项复测通过。按测试标识去重，共150项当前通过；初轮失败XML原样保留，未改生产代码绕过测试。先前72项与本组重叠，不累计。</p><ul>'+''.join('<li>'+esc(x)+'</li>' for x in [
       '电脑保留七个选择，具体原句和质疑草稿刷新后恢复。','仅保存内容质疑时，零模型请求、零画像记录、零分数、零习题；重开仍保留内容。',
       '主动请求导师核对后使用原讲解／资料／模型，保留后来新选的资料；内容质疑不被二次整理进画像。',
       '配对手机恢复混合反馈，仅一条明确自报困难进入画像，质疑文字、分数与自动习题均不进入。',
       '手机核对回到自己的对话与原资料，另一对话的质疑不泄露。'])+'</ul><div class="pair"><figure><img src="desktop-content-check.png" alt="电脑端已保存内容核对"><figcaption>电脑：保存内容核对与具体原句</figcaption></figure><figure><img class="phone" src="phone-mixed-content-check.png" alt="手机端混合反馈"><figcaption>配对 HTTPS 手机：内容核对与明确自报困难</figcaption></figure></div></section>'
    launch='''<section><h2>打开验收</h2><ol><li>关闭旧的 StudyForge 运行实例，双击工作区的 <a href="../../验收最新版.vbs">验收最新版.vbs</a>。这是源码验收入口，需要现有开发环境；已安装的0.4.3未替换，本轮未打包。</li><li>打开一份讲解后的理解反馈，选择“讲解可能有误或依据不清，请先核对”，填写疑点并保存。学习画像不应因此出现新的弱项。</li><li>再点“请导师核对”，观察其针对旧讲解与原资料回应。手机重新加载页面可取得新界面，公共壳版本为v45。</li></ol><p>更多操作已同步到软件内的<a href="../../web/help/guide.html#feedback">零基础使用指南</a>。查看<a href="UI检验记录.json">实际交互记录</a>和<a href="真实模型短例记录.json">两次真实短例记录</a>；这些均为合成测试内容。</p></section>'''
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>内容核对与审核候选对照 · StudyForge</title><style>'+style+'</style><main>'+head+feature+limitations+''.join(sections)+'<section><h2>新增核对入口：两次真实导师短例</h2><p>实际使用共同导师规则、精学模式、直观与专业并重风格及本次内容核对规则。每例一次请求，没有联网、工具、学习画像或整本书上下文；实际界面的接线另由两端受控试验核验。</p>'+''.join(real_blocks)+'</section>'+acceptance+launch+'</main></html>'
    target=OUT/'内容核对与审核候选实际对照.html';target.write_text(page,encoding='utf-8')
    baseline_hash=load(ROOT/'build/review-focus-eval-20261015-1/source-hashes.json')['studyforge/review.py']
    assert hashlib.sha256((ROOT/'studyforge/review.py').read_bytes()).hexdigest()==baseline_hash
    assert (ROOT/'studyforge/review.py').read_bytes()==(ROOT/'build/review-focus-v2-eval-20261015-1/baseline-review.py').read_bytes()
    manifest={'review_requests':20,'real_tutor_requests':2,'regression_tests':len(cases),'actual_ui_checks':5,
              'source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                ('studyforge/lesson_feedback.py','studyforge/review.py','web/lesson_feedback.js','web/mobile/lesson-feedback.js','web/mobile/index.html','web/mobile/sw.js')},
              'rejected_candidates':['original_quote_index','assumptions_and_claim_receipts'],
              'candidate_prompt_boundary_issue_retained':True,'production_review_unchanged':True,
              'regression_xml_files':regression_files,'initial_test_double_failure_retained':True,'packaged':False,'tables':tables}
    (OUT/'验收摘要.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    doc='''# 讲解内容核对与审核候选对照验收

2026-10-15，源码实施；本轮未打包。

## 已完成

- 讲解后理解反馈新增“讲解可能有误或依据不清，请先核对”；原有六类困难保持顺序与含义，可混合选择。
- 可结合现有章节与精确原句定位；未提交草稿在当前设备恢复，提交后保存回原项目与原对话。电脑与手机均可仅保存，保存不请求模型。
- 内容核对沿用原有导师补讲流程与资料／教学配置；先核对原资料、旧讲解与学生主张。成立则说明依据，有误则明确更正，缺少证据则保留待核实，不把既往“核查通过”当作正确性依据。
- 纯内容质疑不建立学习事件、薄弱项或分数；混合反馈只记录明确勾选的六类自报困难，质疑补充文字保留在本份反馈与原对话，不进入画像。历史记录不追溯删除。
- 保留不自动出题、不强制考核与原有可选单题检查。核对结果写回原对话，需要成果修订时可继续向同一导师明确提出。
- 手机反馈标题调整为“理解与内容反馈”；使用指南和可读教学规则同步，公共壳版本v45。

## 程序与交互验收

TEST_COUNT 项最终去重回归通过，覆盖内容核对、原问卷、章节／原句、单题检查、手机接口、学习画像隔离／评分及指南。初轮149通过、1项旧测试替身不接收现有effort参数；更新替身签名后该项复测通过，原失败XML保留，没有修改生产代码绕过该测试。先前72项与本组重叠，不累计。最后只改变手机标题与浏览说明，另以真实页面预览核对。

真实本地后端、Electron桌面与配对HTTPS手机页面完成5项交互：七个选项与精确原句恢复、仅保存零调用／零画像、原资料与当前快选独立、手机混合反馈仅保留明确自报、跨对话范围及无自动评分／出题。2次受控导师请求，0次外部模型请求；控制台错误0。不是安卓实机验收。首个隔离夹具因外键删除顺序启动失败，调整夹具后重建通过；失败文件保留，未涉及用户资料。

## 真实模型证据与限制

审核候选两轮共20次DeepSeek Flash high请求；每轮五例、每例基线／候选各一次，完整输入、最终回答和计时保留，不保存思考文本。候选未进入正式审核，正式review.py与试验前哈希及快照一致。

第一轮原句索引发现一处“别无选择”断言，但长文仍有漏检，对演示数字与来源提示还产生争议；初始数学对照对强弱前提的定义不够明确，不能直接计为干净误报。第二轮逐项回执仍通过含过强断言的长讲解；一份正确短例因附加审核说明被当成待审正文而被拒，首先属于候选接入边界缺陷，不算干净的数学误报对照。两方案均不采用，不据此计算总体准确率、承诺提速或宣称现有审核可靠。

新增核对规则另作2次真实导师组件测试：仅有闭区间前提时正确更正严格端点错误，约8.94秒；严格前提保留时没有附和错误质疑，约27.85秒。每例一次模型请求。样例短、含明确原文，未覆盖完整Agent工具、书库、大文档或真实学生背景；回复仍偏长和重复，不代表整体教学质量已经达标。

## 打开验收

- 先关闭旧StudyForge实例，再双击工作区的 `验收最新版.vbs`；使用当前源码和现有开发环境，本轮不替换安装包。
- 生成讲解后打开理解反馈，选内容核对、填疑点，先仅保存并检查画像，再主动请导师核对。
- 实际对照报告：[内容核对与审核候选实际对照](../build/content-check-review-20261015/内容核对与审核候选实际对照.html)。报告包含全部20次审核、2次真实导师最终回答及两端截图。
- 程序记录：`build/lesson-content-check-final-regression-20261015.xml`及`build/lesson-content-check-regression-recheck-20261015.xml`；按测试标识合并最新结果，初轮失败保留。交互记录：`build/lesson-content-check-ui-20261015-2/ui-report.json`；真实模型：`build/content-check-real-20261015-1/results.json`。
'''.replace('TEST_COUNT',str(len(cases)))
    (ROOT/'docs/讲解内容核对与审核候选对照验收.md').write_text(doc,encoding='utf-8')
    status=ROOT/'docs/当前功能状态与待验收清单.md';text=status.read_text(encoding='utf-8')
    entry=f'2026-10-15 完成 [讲解内容核对与审核候选对照](讲解内容核对与审核候选对照验收.md)：保留六类困难，新增可选内容核对；纯质疑不进画像、不评分，混合反馈仅记录明确选择的自报困难。原对话导师先核对资料与旧讲解，具体原句及设备草稿恢复保持。{len(cases)}项最终去重回归、5项实际电脑／配对HTTPS手机交互通过；2次真实短例区分讲解错误与错误质疑，不能视为整体教学质量保证。20次审核候选对照保留漏检、前提标注歧义和候选提示边界问题，两方案均未集成，未增加自动审核轮次。指南与手机壳v45同步，源码未打包。\n\n'
    marker='## 已有实现及验收记录\n\n'
    if '2026-10-15 完成 [讲解内容核对与审核候选对照]' not in text:
        assert marker in text;status.write_text(text.replace(marker,marker+entry,1),encoding='utf-8')
    print(target)


if __name__=='__main__':main()
