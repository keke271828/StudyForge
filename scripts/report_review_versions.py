"""Record native review-version acceptance without touching user learning data."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import sqlite3
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/review-versions-acceptance-20261025'
UI=ROOT/'build/review-versions-ui-20261025-3'
GATE=ROOT/'build/review-versions-final-20261025'
TITLE='复习原题版本与评分依据验收'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate=load(GATE/'command.json');ui=load(UI/'ui-report.json');state=load(UI/'ui-state.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and len(gate['production_before'])==15
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert ui['passed'] and len(ui['checks'])==4 and ui['controlled_model_calls']==6 and not ui['console_errors']
    assert len(state['submissions'])==4 and len(state['events'])==2 and len(state['sessions'])==2
    assert all(item['active_set_id'] is None for item in state['queue'])
    profiles={item['topic']:item for item in state['profile']}
    assert profiles['高斯定律']['delayed_count']==1 and profiles['相关与因果']['delayed_count']==0
    assert all(item['review_count']==1 for item in profiles.values())
    assert not any(call['changed_parent'] for call in state['calls'])
    db=sqlite3.connect('file:'+str(UI/'data/studyforge.sqlite3')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    documents=[]
    for item in ui['completed']:
        artifact=dict(db.execute('SELECT * FROM artifacts WHERE id=?',(item['feedback_artifact_id'],)).fetchone())
        path=Path(artifact['path'])
        with ZipFile(path) as archive:
            assert archive.testzip() is None
            root=ET.fromstring(archive.read('word/document.xml'))
            text='\n'.join(''.join(p.itertext()) for p in root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
        assert '90' in text and '针对性讲解' in text and '作答条件' in text and 'NEW_PARENT' not in text
        assert ('本次按保存的原题与评分版本复习' if item['version_verified'] else '不把这段间隔当作已验证的同题延迟证据') in text
        name='保存原题版本_批改与补讲' if item['version_verified'] else '旧版本未核实_批改与补讲'
        documents.append({'source':path,'filename':name+'.docx','text_name':name+'.txt','body':text,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'version_verified':item['version_verified']})
    db.close()
    if OUT.exists():raise SystemExit('Preserve earlier acceptance evidence.')
    OUT.mkdir()
    for item in documents:
        shutil.copy2(item['source'],OUT/item['filename'])
        (OUT/item['text_name']).write_text(item['body'],encoding='utf-8')
    report={'date':'2026-10-25','gate':gate,'ui':ui,'seed_submissions':2,'native_submissions':2,'assessment_events':2,
        'review_sessions':2,'documents':[{key:value for key,value in item.items() if key not in ('source','body')} for item in documents],
        'packaged':False,'limits':['controlled grades, not model quality','no physical Android check',
            'Word package and text checked, not pagination','no global speed or memory benchmark']}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    total=gate['tests']['total']
    samples=''.join('<details><summary>'+('有版本证据的复习' if item['version_verified'] else '旧记录版本未知的首次复习')+
        '</summary><p><a href="'+item['filename']+'">下载原生批改 Word</a> · <a href="'+item['text_name']+
        '">查看正文文本</a></p><pre>'+html.escape(item['body'])+'</pre></details>' for item in documents)
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>复习原题版本与评分依据验收</title><style>
:root{color:#233e36;background:#eeeee8;font:16px/1.85 "Microsoft YaHei",sans-serif;color-scheme:light}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:28px 20px 65px}header,section{background:#fffef9;border:1px solid #d8dfd5;border-radius:20px;padding:25px 30px;margin:0 0 20px}h1{font-size:30px;line-height:1.45}h2{font-size:23px}.eyebrow{font-size:13px;letter-spacing:.1em;color:#517769}a{color:#146b58;text-underline-offset:3px}.good,.note{padding:16px 20px;border-radius:13px}.good{background:#e7f2e9}.note{background:#fff0da;border-left:4px solid #c48d38}table{border-collapse:collapse;width:100%}th,td{vertical-align:top;text-align:left;padding:12px;border-bottom:1px solid #dce2d8}li{margin:9px 0}img{display:block;max-width:100%;border:1px solid #d7dfd6;border-radius:14px;margin:18px auto}.phone{max-width:320px}details{border:1px solid #dce2d8;border-radius:14px;padding:15px 18px;margin:16px 0}summary{font-weight:650;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f3ed;padding:18px;border-radius:12px;font:14px/1.9 "Microsoft YaHei",sans-serif}@media(max-width:650px){main{padding:14px 9px}header,section{padding:20px 16px}h1{font-size:25px}table{font-size:14px}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-25 · SOURCE ACCEPTANCE</div><h1>复习和评分使用同一份原题</h1><p>原来复习安排只保存题单和题号，开始复习时会重新读取当前题面与答案。原题后来修改，就可能把新题当作旧题复习；批改期间改变评分依据，也可能保存不匹配的分数。本轮补齐版本保存、评分检查和历史证据边界。</p><p><a href="../../验收最新版.vbs">最新版源码启动入口</a> · <a href="../../web/help/guide.html#homework">软件内指南</a> · <a href="report.json">验收摘要与文档指纹</a></p><p>先从 Windows 托盘彻底退出旧 StudyForge，再在资源管理器双击“验收最新版.vbs”；手机连接后刷新。本轮更新源码，未打包。</p></header>
<section><h2>实际改变</h2><table><tr><th>场景</th><th>现在的处理</th></tr><tr><td>加入复习后，来源题目、参考解、评分标准或参考难度改变</td><td>沿用加入时保存的内容，队列保留原知识点并提示“原题已更新”。改过的新内容不会静默替换旧安排。</td></tr><tr><td>尚未排入复习的题，已经与上次评分版本不同</td><td>明确要求完成当前版本后再安排。只修改另一道未选题，不会阻止仍与旧评分一致的所选题。</td></tr><tr><td>批改中途修改题目；或据已改变的新题复核旧作答</td><td>停止保存不匹配的分数与画像证据。版本冲突不自动重试模型；重试请求无法恢复丢失的题源依据。</td></tr><tr><td>旧记录没有可核实的题目版本</td><td>仍可练习与评分，电脑、手机及批改 Word 均说明边界；不会把历史间隔计作已核实的同题延迟证据。能对应到相同提交与答案的旧详细作业版本可继续使用。</td></tr><tr><td>旧题完成一次新的、版本已保存的复习</td><td>建立此后的新基准，下一次才能按该已知版本核对；已经记录的第一次未知间隔不被追认。</td></tr><tr><td>混合复习、重命名及 JSON 格式变化</td><td>分别保留每题依据；混合题单的平均参考难度不使单题变成“另一题”。仅重命名或格式化 JSON 不制造题源变化。</td></tr></table><p class="good">版本比较在本机完成，没有增加固定模型审查轮数。私有参考解和评分标准保存在服务端，提交前的队列与公开题单不提供答案。</p><p class="note">版本一致只能证明“核对的是哪份内容”，不能证明参考答案本身正确，也不能证明单次高分等于稳定掌握。</p></section>
<section><h2>电脑与配对手机的实际流程</h2><ol><li>准备两道已提交的合成原题：一道保留版本依据，一道模拟旧版记录缺失。均安排约 72 小时后的复习。</li><li>安排完成后，修改第一道来源题的题干、知识点、参考解、标准及难度。电脑仍显示保存的原知识点，并提示来源已更新。</li><li>分别从电脑创建复习，通过真实 HTTPS 配对手机打开。题面仍是保存版本，未提交前无参考答案；旧记录另有未核实提示。</li><li>手机逐份完整提交，原生评分、错因补讲与 Word 下载完成。有证据的题记录 1 次已核实同题延迟作答；旧记录第一次为 0，但两题各自的复习作答均保留。</li><li>评分桩收到的两次第一题核查都含保存的题面和标准，没有收到修改后的来源标记。再次打开没有新评分、新题单或额外模型请求。</li></ol><img src="../review-versions-ui-20261025-3/desktop-saved-versions.png" alt="电脑队列分别显示原题更新后使用保存版本和旧记录未核实提示"><details><summary>展开 320px 深色手机的旧版本提示</summary><img class="phone" src="../review-versions-ui-20261025-3/phone-legacy-version.png" alt="手机提交前显示旧题版本未核实且不作为已验证同题延迟证据"></details></section>
<section><h2>验证结果</h2><p>最终 __TOTAL__ 项关联回归全部通过，失败、错误、跳过均为 0；15 个生产文件前后指纹一致。新增针对性 28 项覆盖内容替换、标准修改、批改中途变更、混合难度、旧库升级、快照损坏、删除清理及未知基准转为新基准等情况。6 项相关 JavaScript 语法检查通过。</p><p>4 组电脑／配对 HTTPS 手机检查通过，控制台错误 0。共有 2 份原题提交种子、2 份原生复习提交、2 条新增逐题评估和 2 个复习会话；评分与补讲共 6 次受控调用，真实云调用 0。两份原生批改 DOCX 均下载并核对压缩包、正文和指纹；指南和手机壳 v76 同步。</p><p><a href="../review-versions-final-20261025/command.json">最终命令与源码指纹</a> · <a href="../review-versions-final-20261025/regression.xml">最终回归 XML</a> · <a href="../review-versions-ui-20261025-3/ui-report.json">两端操作记录</a> · <a href="../review-versions-ui-20261025-3/ui-state.json">隔离验收状态</a> · <a href="../review-versions-red-20261025.xml">修复前的针对性失败记录</a></p><details><summary>过程中的记录</summary><p>修复前 14 项目标行为失败，不等于 14 个独立故障。核心 14 项、中途 115 项和后续 124 项检查均通过，与最终范围重叠，不相加。首次 UI 已完成有版本题的提交，随后因脚本要求“旧作答”而实际提示为“旧版本未核实”停下；修正匹配后完整通过。最终截图又等待上一题临时通知消失，避免通知与当前题目混淆。没有为测试放宽生产校验。</p></details><p class="note">本轮验证版本、评分记录与交付链路，评分和补讲内容来自验收桩，不作真实模型教学质量认证。使用真实配对 HTTPS 及手机尺寸窗口，未重测实体安卓、Word 分页或全软件内存与长任务速度。原始模型、通过线、审查轮数和项目聊天隔离不因本项改变。</p></section>
<section><h2>已完整提交的合成批改样例</h2><p>下面两份文档来自本次原生提交流程，均为受控 90 分，用来核对版本说明，不用于评价模型教学水平。</p>__SAMPLES__</section></main></html>'''
    (OUT/(TITLE+'.html')).write_text(page.replace('__TOTAL__',str(total)).replace('__SAMPLES__',samples),encoding='utf-8')
    doc=f'''# 复习原题版本与评分依据验收

2026-10-25，源码更新，未打包。

## 修改

- 新复习安排保存私有原题、参考解、评分标准与参考难度；来源改变仍用保存版本，并显示提示。提交前公开队列和题单不泄露答案。
- 新评分写入服务端生成的内容指纹。已知版本不匹配时不复核旧作答；评分期间改变依据不保存不匹配分数和画像证据。版本冲突不自动重复模型请求。
- 旧记录没有依据时保留练习和评分，不冒认同题延迟证据；相同提交、项目和答案对应的历史详细作业版本可核实。新的实际完成建立未来基准，不追认过去未知间隔。
- 混合难度保留单题身份；题单重命名或 JSON 排版变化不误判。损坏快照明确停止，不回退替换当前题。
- 电脑练习、作业提交、手机及批改 Word 同步说明；本机比较不增加固定模型审查。指南与手机壳 v76 同步。

## 验证

- 最终 {total} 项关联回归通过，失败／错误／跳过均 0，15 个生产文件前后指纹一致；新增针对性 28 项，相关 6 项 JavaScript 语法检查通过。
- 修复前 14 项目标行为失败；核心 14、中途 115、后续 124 项通过，与最终范围重叠不相加。
- 4 组实际电脑／配对 HTTPS 手机检查通过，控制台错误 0。2 份种子原提交、2 份原生复习提交、2 条新增评估、2 个会话；受控 6 请求，云调用 0。
- 先安排再修改原题、标准与难度，手机仍拿到保存版本；两个评分核查均收到旧题旧标准，未收到新来源标记。已知版延迟计数 1，未知旧基准首次计数 0，原作答仍保留。
- 两份原生 DOCX 下载、压缩包、正文和指纹核对通过。首次 UI 为提示文本匹配差异，修正脚本后完成；最终截图等待上一题临时通知消失。没有放宽生产规则。

## 打开和边界

从 Windows 托盘彻底退出旧 StudyForge，在资源管理器双击“验收最新版.vbs”；手机连接后刷新。

验收页：[复习原题版本与评分依据验收.html](C:/Users/Lenovo/Documents/ChatGPT/codex workspace/build/review-versions-acceptance-20261025/复习原题版本与评分依据验收.html)

版本指纹证明身份不证明答案正确；单次分数不证明掌握。本轮使用受控模型，不认证真实教学、实体安卓、Word 分页或整体性能；未打包，未新增关机动作。
'''
    (ROOT/'docs/复习原题版本与评分依据验收.md').write_text(doc,encoding='utf-8')
    path=ROOT/'docs/当前功能状态与待验收清单.md';status=path.read_text(encoding='utf-8')
    entry=f'2026-10-25 完成 [复习原题版本与评分依据](复习原题版本与评分依据验收.md)：补齐上条队列验收留下的内容变更边界，保存原题／参考解／标准与单题难度，来源改变不替换旧复习；评分前后核对版本，版本冲突不重复请求。旧版本未知仍可练习但不冒认同题延迟，新的实际完成只建立未来基准。最终{total}项关联回归（新增28项）、4组电脑／配对HTTPS检查及6项语法检查通过，15个生产文件指纹一致；原生复习2份、评估2条、会话2个，受控6请求、云调用0。两份Word下载／正文／压缩包已核对，不认证模型质量、实体安卓、分页或整体性能；指南和手机壳v76，源码未打包。\n\n'
    if '[复习原题版本与评分依据]' not in status:
        path.write_text(status.replace('## 已有实现及验收记录\n\n','## 已有实现及验收记录\n\n'+entry,1),encoding='utf-8')
    print(json.dumps({'report':str(OUT/(TITLE+'.html')),'tests':total,'native_documents':len(documents)},ensure_ascii=False))


if __name__=='__main__':main()
