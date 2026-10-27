"""Preserve native review lifecycle acceptance and its delivered feedback."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import sqlite3
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/review-queue-acceptance-20261025'
UI=ROOT/'build/review-queue-ui-20261025-3'
GATE=ROOT/'build/review-queue-final-20261025'
TITLE='复习队列范围与项目恢复验收'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate=load(GATE/'command.json');ui=load(UI/'ui-report.json');state=load(UI/'ui-state.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert len(ui['checks'])==4 and ui['controlled_model_calls']==3
    assert len(state['sessions'])==1 and len(state['submissions'])==3 and len(state['events'])==2
    assert all(item['active_set_id'] is None for item in state['queue'])
    if OUT.exists():raise SystemExit('Preserve earlier acceptance files.')
    OUT.mkdir()
    db=sqlite3.connect('file:'+str(UI/'data/studyforge.sqlite3')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    artifact=dict(db.execute('SELECT * FROM artifacts WHERE id=?',(ui['feedback_artifact_id'],)).fetchone());db.close()
    target=OUT/'手机完成混合复习_批改与补讲.docx';shutil.copy2(artifact['path'],target)
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        document=ET.fromstring(archive.read('word/document.xml'))
        body='\n'.join(''.join(p.itertext()) for p in document.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
    assert '90' in body and '相关与因果' in body and '高斯定律' in body and '作答条件' in body
    (OUT/'原生批改正文.txt').write_text(body,encoding='utf-8')
    report={'date':'2026-10-25','gate':gate,'ui':ui,'review_session_count':1,'seed_submissions':2,'native_review_submissions':1,
        'new_assessment_events':2,'artifact':{'filename':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'package_verified':True},
        'limits':['controlled scores','no physical Android verification','no Word pagination verification','no full performance claim'],'packaged':False}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    total=gate['tests']['total']
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>复习队列范围与项目恢复验收</title><style>
:root{color-scheme:light;color:#243e35;background:#efeee8;font:16px/1.85 "Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:30px 20px 65px}header,section{background:#fffdf8;border:1px solid #d8dfd5;border-radius:20px;padding:26px 30px;margin-bottom:20px}h1{font-size:30px;line-height:1.4}h2{font-size:23px}.eyebrow{font-size:13px;letter-spacing:.12em;color:#4d7868}.good,.note{border-radius:12px;padding:16px 20px}.good{background:#e8f3eb}.note{background:#fff0d8;border-left:4px solid #bc8a35}a{color:#116c58;text-underline-offset:3px}li{margin:8px 0}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #dce1d7;text-align:left;vertical-align:top}img{max-width:100%;display:block;border:1px solid #dce1d7;border-radius:14px;margin:15px auto}.phone{max-width:320px}details{border:1px solid #dce1d7;border-radius:14px;padding:14px 18px;margin:15px 0}summary{font-weight:650;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f3ed;padding:18px;border-radius:12px;font:14px/1.9 "Microsoft YaHei",sans-serif}@media(max-width:650px){main{padding:14px 9px}header,section{padding:20px 16px}h1{font-size:25px}table{font-size:14px}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-25 · SOURCE ACCEPTANCE</div><h1>复习可以可靠地恢复与续接</h1><p>修复回收站项目仍出现在复习队列、旧勾选可复制隐藏原题，以及部分选择被当作完整旧题单复用的问题。</p><p><a href="../../验收最新版.vbs">最新版源码启动入口</a> · <a href="../../web/help/guide.html#homework">软件内指南</a> · <a href="report.json">验收摘要与文档指纹</a></p><p>先从Windows托盘彻底退出旧StudyForge，在资源管理器双击“验收最新版.vbs”；手机连接后刷新。本次更新源码，未打包。</p></header>
<section><h2>本轮改动</h2><table><tr><th>情况</th><th>现在的行为</th></tr><tr><td>题目来源项目在回收站</td><td>队列、分页总数、到期计数同步暂时排除，原复习安排保留；恢复项目后重新出现。旧勾选也不能把隐藏题目复制进其他项目。</td></tr><tr><td>正在作答的混合复习所在项目在回收站</td><td>不再留下点开后404的“继续作答”。恢复该项目后仍可打开同一题单，不另建一份。</td></tr><tr><td>重复请求已有混合复习</td><td>仅当完整选题范围相同且相关项目仍可用时复用；部分选择不会悄悄打开更大的旧题单。</td></tr><tr><td>队列刷新、跨页勾选</td><td>最多核对6个已选ID，移除失效／进行中的选择，保留其他页有效项；等待刷新期间新勾选的有效题目不会被旧响应抹去。</td></tr><tr><td>完成复习</td><td>保留原题来源和开题间隔，按原设间隔安排下一次；打开、恢复、勾选不算一次新作答。</td></tr></table><div class="good">跨项目主动复习保留。原题、成绩、画像证据和复习安排不会因为临时隐藏而删除；没有新增固定模型审查或更换教师提示词。</div><p>本轮还把混合复习标题的日期从固定东八区改为电脑本机日期。手机继续使用已有的作业入口完成电脑创建的题单，本轮未新增手机端队列管理界面。</p></section>
<section><h2>实际流程</h2><ol><li>准备两个项目中的已提交原题和两项到期安排。电脑队列显示两项；一次延迟刷新期间新勾选另一项，选择仍保留。</li><li>回收一个来源项目，队列变为一项、到期数变为一项，旧勾选清理，数据库仍保留两项原安排；恢复后再次选齐两项。</li><li>在复习工作区创建一份两题混合复习，答案仍隐藏。只请求其中一项时，接口拒绝把整份两题题单当成匹配结果。</li><li>回收复习工作区，失效继续入口暂时隐藏。恢复后“继续作答”打开原题单，重复完整选择复用同一ID，没有新模型请求。</li><li>配对HTTPS手机完整提交这两题，原生评分与补讲完成，下载批改Word。原复习开题间隔约72小时保留，两项队列清除进行中标记并进入下一次安排。</li></ol><img src="../review-queue-ui-20261025-3/desktop-restored-review.png" alt="恢复项目后电脑复习队列指向同一份混合题单"><details><summary>展开320px深色手机截图</summary><img class="phone" src="../review-queue-ui-20261025-3/phone-completed-review.png" alt="手机完成同一份混合复习并提供原生解析与批改下载"></details></section>
<section><h2>验证与保留记录</h2><p>修复前9项针对性检查失败，复现回收站可见性、保留ID复制、范围错误复用及重排隐藏原题；最终新增针对性12项。中途37项聚焦检查通过，与最终范围重叠不相加。</p><p>最终__TOTAL__项关联回归全部通过，失败、错误、跳过均0，5个生产文件前后指纹一致。4组实际电脑／配对HTTPS手机操作通过，控制台错误0；3个相关JavaScript文件语法检查通过，指南和手机壳v75同步。</p><p>此次UI共有两份原题提交种子与一份原生复习提交，只有一个混合复习会话、两个新逐题作答证据；查看、恢复、复用没有额外测验。评分和补讲共3次受控调用，真实云调用0。两项评估记录了原复习间隔与自报未查笔记，这仍不是对独立完成或长期保持的验证。</p><p><a href="../review-queue-final-20261025/command.json">最终命令和指纹</a> · <a href="../review-queue-final-20261025/regression.xml">最终回归XML</a> · <a href="../review-queue-ui-20261025-3/ui-report.json">实际两端检查</a> · <a href="../review-queue-ui-20261025-3/ui-state.json">隔离验收状态</a> · <a href="../review-queue-red-20261025.xml">修复前失败记录</a></p><details><summary>中途验收脚本问题</summary><ul><li>第一次UI在被另一次刷新替代时过早断言，保存截图中的最终队列已正确；改为等待最终界面状态。</li><li>第二次脚本直接回收当前项目后又试图保存旧项目草稿，受到已有回收站保护拦截。改为先正常切换，再回收复习所在项目；生产代码没有为脚本放开归属检查。</li></ul></details><p class="note">本轮验证复习安排、项目边界和交付链路，不评价真实模型教学或评分质量。原评分与回答由验收桩提供；未重测实体安卓、Word分页或全软件内存／长任务速度。只读或恢复记录不证明掌握；题目正文／评分标准后来改变时的完整版本绑定仍建议另作专门核验，本轮没有声称解决所有题源变更问题。</p></section>
<section><h2>原生批改文档</h2><p>以下来自这次已完整提交的合成复习答案。</p><p><a href="手机完成混合复习_批改与补讲.docx">下载批改与补讲Word</a> · <a href="原生批改正文.txt">查看正文文本</a></p><details><summary>展开原生批改正文</summary><pre>__BODY__</pre></details></section></main></html>'''
    (OUT/(TITLE+'.html')).write_text(page.replace('__TOTAL__',str(total)).replace('__BODY__',html.escape(body)),encoding='utf-8')
    doc=f'''# 复习队列范围与项目恢复验收

2026-10-25，源码更新，未打包。

## 修改

- 来源项目或正在进行的复习所在项目在回收站时，队列、分页总数、到期计数同步暂时排除，原安排保留；恢复项目后可继续原题单。旧ID不能复制回收站题目或向回收站目标项目创建复习。
- 复用进行中的混合复习时核对完整选择范围，不把子集当作原整份题单；保留反序同范围复用。原题跨项目已不可用时，不能通过重排已完成复习修改隐藏来源安排。
- 队列刷新仅查询最多6个已选ID的可用性，清理失效／已开始项，保留跨页有效选择及等待期间新勾选。空／过量参数明确报错，不写数据。
- 混合复习标题改为本机日期。原分数、模型、教师提示词、评分标准与复习间隔策略不改；指南与手机壳v75同步。

## 验证

- 修复前9项针对性失败，新增最终12项；中途37项聚焦检查通过，与最终范围重叠不累加。
- 最终{total}项关联回归全部通过，失败／错误／跳过均0；5个生产文件指纹一致。相关3个JavaScript文件语法检查通过。
- 4组实际电脑／配对HTTPS手机操作通过：回收来源及到期／勾选清理，延迟刷新保留新勾选，完整范围复用，回收恢复复习所在项目后同ID打开，手机完整提交、间隔保留和原生Word下载。控制台错误0。
- 两份原题为合成已提交种子，新混合复习只有1份原生提交、2条逐题画像评估、1个会话；受控模型3请求，真实云调用0。恢复和查看不增加评分／模型请求；完成后仍为两项原安排，按已设间隔续排。
- 首次UI过早断言和第二次脚本回收当前项目后试图保存旧草稿均保留记录，修正脚本后完整通过，没有放宽生产归属检查。DOCX核对压缩包、正文与指纹，截图已检查。

## 打开及边界

从Windows托盘彻底退出旧StudyForge，资源管理器双击“验收最新版.vbs”；手机连接后刷新，使用“作业”完成电脑创建的复习。本轮未新增手机队列管理界面。

验收页：[复习队列范围与项目恢复验收.html](C:/Users/Lenovo/Documents/ChatGPT/codex workspace/build/review-queue-acceptance-20261025/复习队列范围与项目恢复验收.html)

本轮不认证真实模型教学质量、实体安卓、Word分页或整体性能。后续应专门核验原题正文／评分标准变化后的版本绑定，不能据本轮声称全部题源变更已处理。源码未打包，未新增关机动作。
'''
    (ROOT/'docs/复习队列范围与项目恢复验收.md').write_text(doc,encoding='utf-8')
    path=ROOT/'docs/当前功能状态与待验收清单.md';status=path.read_text(encoding='utf-8')
    entry=f'2026-10-25 完成 [复习队列范围与项目恢复](复习队列范围与项目恢复验收.md)：回收站来源／复习所在项目与队列计数同步隐藏、恢复仍续接原题单；旧ID不能复制隐藏原题，已有混合复习核对完整选择，刷新保留跨页有效及等待期间新勾选。最终{total}项关联回归、4组实际电脑／配对HTTPS操作通过，5个生产文件指纹一致；原生复习提交1份、逐题评估2条、会话1个，受控3请求、云调用0。Word下载／压缩包／正文核对通过，不认证真实模型教学、实体安卓、分页或整体性能；题源内容变更的完整版本绑定仍需专门核验。指南与手机壳v75同步，源码未打包。\n\n'
    if '[复习队列范围与项目恢复]' not in status:path.write_text(status.replace('## 已有实现及验收记录\n\n','## 已有实现及验收记录\n\n'+entry,1),encoding='utf-8')
    print(json.dumps({'report':str(OUT/(TITLE+'.html')),'tests':total,'native_docx':target.name},ensure_ascii=False))


if __name__=='__main__':main()
