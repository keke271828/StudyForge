"""Preserve native submitted-work deliverables and local acceptance evidence."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import sqlite3
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/repair-readiness-acceptance-20261023'
UI=ROOT/'build/repair-readiness-ui-20261023-3'
GATE=ROOT/'build/repair-readiness-final-20261023'
TITLE='错因补讲完成与再练续接验收'


def read_json(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate=read_json(GATE/'command.json');ui=read_json(UI/'ui-report.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert ui['grading_calls']==2 and ui['controlled_model_calls']==5
    if OUT.exists():raise SystemExit('Use preserved report; do not overwrite acceptance evidence.')
    OUT.mkdir()
    database=sqlite3.connect('file:'+str(UI/'data/studyforge.sqlite3')+'?mode=ro',uri=True)
    database.row_factory=sqlite3.Row
    attempt=dict(database.execute('SELECT * FROM homework_attempts WHERE id=?',(ui['attempt_id'],)).fetchone())
    worksheet=dict(database.execute('SELECT * FROM exercise_sets WHERE id=?',(attempt['exercise_set_id'],)).fetchone())
    submission=list(database.execute('SELECT id,score FROM submissions WHERE exercise_set_id=?',(worksheet['id'],)))
    assert len(submission)==1 and submission[0]['score']==95 and attempt['status']=='completed'
    artifacts=[]
    for field,label in [('solution_artifact_id','原题与答案解析_已完整提交'),('feedback_artifact_id','批改与错题讲解_恢复原批改')]:
        row=dict(database.execute('SELECT * FROM artifacts WHERE id=?',(attempt[field],)).fetchone())
        target=OUT/(label+'.docx');shutil.copy2(row['path'],target)
        with ZipFile(target) as archive:
            assert archive.testzip() is None
            document=ET.fromstring(archive.read('word/document.xml'))
            text='\n'.join(''.join(p.itertext()) for p in document.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
        (OUT/(label+'.txt')).write_text(text,encoding='utf-8')
        if field=='feedback_artifact_id':
            assert '95' in text and '净通量' in text and '学生自报' in text and '计算2+3' in text
        artifacts.append({'id':row['id'],'filename':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                          'package_verified':True,'text':text})
    database.close()
    report={'date':'2026-10-23','scope':'repair readiness and explicit recovery; no new model quality claim',
        'gate':gate,'ui':ui,'submission_count':len(submission),'score':submission[0]['score'],
        'artifacts':artifacts,'source_packaged':False,'shutdown_requested_this_turn':False}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    total=gate['tests']['total']
    docs=''.join('<details><summary>'+html.escape(item['filename'])+' · 原生正文</summary><pre>'+html.escape(item['text'])+'</pre></details>' for item in artifacts)
    content='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>错因补讲完成与再练续接验收</title><style>
:root{color-scheme:light;color:#243e35;background:#efeee8;font:16px/1.85 "Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:30px 20px 65px}header,section{background:#fffdf8;border:1px solid #d8dfd5;border-radius:20px;padding:26px 30px;margin-bottom:20px}h1{font-size:30px;line-height:1.4}h2{font-size:23px}.eyebrow{font-size:13px;letter-spacing:.12em;color:#4d7868}.good,.note{border-radius:12px;padding:16px 20px}.good{background:#e8f3eb}.note{background:#fff0d8;border-left:4px solid #bc8a35}a{color:#116c58;text-underline-offset:3px}li{margin:8px 0}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #dce1d7;text-align:left;vertical-align:top}img{max-width:100%;display:block;border:1px solid #dce1d7;border-radius:14px;margin:15px auto}.phone{max-width:320px}details{border:1px solid #dce1d7;border-radius:14px;padding:14px 18px;margin:15px 0}summary{font-weight:650;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f3ed;padding:18px;border-radius:12px;font:14px/1.9 "Microsoft YaHei",sans-serif}@media(max-width:650px){main{padding:14px 9px}header,section{padding:20px 16px}h1{font-size:25px}table{font-size:14px}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-23 · SOURCE ACCEPTANCE</div><h1>先完成错因补讲，再按当前卡点练</h1><p>继续完善学习链路：防止批改尚未完成时只按分数再出一套题，并让保留的取消任务能明确恢复。</p><p><a href="../../验收最新版.vbs">最新版源码启动入口</a> · <a href="../../web/help/guide.html#homework">软件内指南</a> · <a href="report.json">验收摘要与文档指纹</a></p><p>先从Windows托盘彻底退出旧StudyForge，再在资源管理器双击“验收最新版.vbs”。手机重新连接后刷新。本次源码更新，未打包EXE。</p></header>
<section><h2>本轮改动</h2><table><tr><th>情况</th><th>现在怎样继续</th></tr><tr><td>已评分，但错因分析、问卷或补讲未完成</td><td>先继续原批改；匹配本次作答的详细记录未完成时，接口也拒绝提前生成修复目标，不退回只按分数出题。</td></tr><tr><td>批改失败</td><td>在作业记录点“重试批改”（手机为“重试原批改”），使用已保存的作答与完成步骤。</td></tr><tr><td>项目移入回收站后恢复，原任务已取消</td><td>未删除的作业记录提供“继续原批改”。如果停在错因问卷，先恢复问卷，不启动新的模型请求；提交澄清后再继续补讲。</td></tr><tr><td>题目只得90分等部分分数</td><td>电脑普通练习页显示该失分项的暂定卡点，并默认勾选加入复习；再练仍等详细补讲完成后由你决定。</td></tr><tr><td>满分或原有费曼流程</td><td>满分不显示错因再练按钮；选择原有流程的题单仍先完成费曼环节。旧普通题单确无详细批改记录时保留原有练习方式，不冒称已知错因。</td></tr></table><div class="good">这次没有增加默认审查轮次、加长教师提示词或自动生成新题。恢复已完成的评分步骤，不增加一次作答，也不把看过补讲当成已经掌握。</div><p>已删除的任务不能恢复；题目版本改变、项目不匹配或旧任务尚在取消收尾时，继续操作会被拒绝。普通任务更新仍不能把取消或删除的任务自行复活，只有明确点击继续的专用路径可恢复保留记录。</p></section>
<section><h2>实际两端流程</h2><ol><li>电脑原生提交两题，受控评分90／100，总分95。失分题的暂定卡点保留；详细分析未完时没有再练按钮，直接请求选题接口也被拒绝。</li><li>将隔离项目移入回收站再恢复：分析被取消，已保存的原提交与95分保留。</li><li>配对HTTPS手机点击“继续原批改”，不重复两次评分核查，恢复原错因问卷。</li><li>提交“我把净通量误当成了各点的电场……”后，完成针对性补讲与原生Word交付；仅第1题出现为再练选项，保留“学生自报，未独立验证”。</li><li>满分旧题单没有错因再练入口。打开选题窗口没有创建题单或新任务；已完成的批改DOCX通过手机下载接口取得有效Word包。</li></ol><img src="../repair-readiness-ui-20261023-2/desktop-wait-for-teaching.png" alt="电脑95分部分失分卡点保留，未完成补讲时显示恢复入口"><details><summary>320px深色手机 · 补讲后才选择再练范围</summary><img class="phone" src="../repair-readiness-ui-20261023-2/phone-ready-selected-target.png" alt="手机只选实际失分项，学生自报边界保留"></details></section>
<section><h2>检验结果与保留的失败记录</h2><p>最终 __TOTAL__ 项关联回归全部通过，失败、错误和跳过均0；8个生产文件在测试前后指纹一致。5项实际电脑／配对HTTPS交互通过，控制台错误0；5个相关JavaScript文件通过语法检查，手机静态壳已更新到v73。</p><p>共5次受控模型调用尝试：2次评分、3次分析（其中1次被取消），真实云调用0。恢复过程保留一份原提交和95分，没有新练习任务。新针对性20项包含未完成依赖、取消恢复、原问卷续接、旧工作线程收尾及已删除／错误归属／题目变更等边界；与最终回归重叠，不另行累加。</p><details><summary>修复前后记录，不只保留成功结果</summary><ul><li>修复前依赖检查12项失败、2项通过；保留的取消任务恢复检查2项失败，均为有效复现。</li><li>首次聚焦检查33项通过、2项失败，发现普通状态更新的取消保护也拦住了明确恢复。随后增加限定归属、状态和删除检查的恢复入口，没有放宽全局保护。16项针对性检查通过后，再加4项恢复边界检查纳入最终回归。</li><li>第一次UI完成前三步后，因脚本用不存在的按钮属性定位而失败；修正为实际文字操作，重新完整运行通过。同时统一手机入口条件，避免旧题单状态绕过可再练状态。</li></ul></details><p><a href="../repair-readiness-final-20261023/command.json">最终命令与源码指纹</a> · <a href="../repair-readiness-final-20261023/regression.xml">最终回归XML</a> · <a href="../repair-readiness-ui-20261023-2/ui-report.json">实际UI记录</a> · <a href="../repair-readiness-red-20261023.xml">依赖问题修复前</a> · <a href="../repair-readiness-cancel-red-20261023.xml">取消恢复修复前</a></p><p class="note">本轮验证学习步骤衔接、恢复与原生交付；固定分数和补讲由测试桩提供，不据此判断真实模型教学或评分质量。手机使用真实HTTPS网关与手机尺寸窗口，未重测实体安卓；Word已核对压缩包与正文，未进行Word分页验收。本次不宣称长视频、生成速度或全软件内存改善，也未打包。</p></section>
<section><h2>可打开的原生文档</h2><p>两份样例均来自这次已完整提交的合成作答，解析先交付，批改补讲后交付。</p><p><a href="原题与答案解析_已完整提交.docx">原题与答案解析</a> · <a href="批改与错题讲解_恢复原批改.docx">批改与错题讲解</a></p>__DOCS__</section></main></html>'''
    content=content.replace('../repair-readiness-ui-20261023-2/','../'+UI.name+'/')
    (OUT/(TITLE+'.html')).write_text(content.replace('__TOTAL__',str(total)).replace('__DOCS__',docs),encoding='utf-8')
    documentation=f'''# 错因补讲完成与再练续接验收

2026-10-23，源码更新，未打包。

## 修改

- 匹配本次作答的详细批改尚未完成时，不允许退回只按分数生成修复目标；完成补讲和任务交付后才开放定向再练。
- 电脑作业记录与手机提供明确的恢复入口：失败可重试，项目移入回收站并恢复后，保留的取消批改可继续。已评分的步骤复用；原错因问卷未完成时先恢复为等待填写，不直接生成批改文档。
- 恢复专用入口保留项目、对话、原题版本、任务删除和旧工作线程收尾检查。全局取消／删除保护不放宽；已删除任务不能恢复。
- 电脑普通练习页的暂定卡点与默认复习选项覆盖全部失分项，包括90分题；满分不显示错因再练入口。手机再练入口统一采用可再练状态，不用旧题单状态绕过。
- 原有费曼流程、80分通过线、旧普通题单没有详细记录时的原有练习方式保留。没有增加默认核查轮次、自动出题或加长教师提示词。指南和手机静态壳v73同步。

## 验证

- 修复前依赖检查12项失败、2项通过；取消恢复2项失败，均为有效复现。首次聚焦33项通过、2项失败发现取消保护拦住明确恢复，修复后16项通过，再新增4项恢复边界检查纳入最终回归。
- 最终{total}项关联回归全部通过，失败／错误／跳过均0；8个生产文件测试前后指纹一致。5个相关JavaScript文件语法检查通过。
- 实际电脑和配对HTTPS手机5项交互通过：原生提交两题，受控90／100总分95；未完成补讲时暂定卡点可见但再练被拒绝；实际项目回收／恢复取消分析并保留成绩；电脑显示恢复入口；手机恢复原批改、等待问卷、提交澄清后完成补讲与Word交付；仅第1题为自愿再练目标；满分旧题单不显示错因再练。
- 5次受控调用尝试中，评分2次、分析3次（1次被取消），真实云调用0。保留1份原提交和95分，没有自动创建新题单或练习任务。查看选题不调用模型。
- 两份原生DOCX来自已完整提交的合成作答，已核对压缩包、正文与文件指纹；批改文档通过手机下载接口。第一次UI因脚本查找不存在的按钮属性而失败，修正为实际文字操作后完整重跑；最终UI控制台错误0。320px深色手机和电脑截图已检查。

## 边界与打开方式

这是学习流程与交付验证。固定分数和补讲来自测试桩，不证明真实模型评分或教学质量提升；未重新验收实体安卓、Word分页、长任务速度或整体内存。原生修复选题窗口实际打开，本次UI没有点击生成新题；生成逻辑由关联回归覆盖。

从Windows托盘彻底退出旧StudyForge，再在资源管理器双击“验收最新版.vbs”；手机连接后刷新。

可打开验收页：[错因补讲完成与再练续接验收.html](C:/Users/Lenovo/Documents/ChatGPT/codex workspace/build/repair-readiness-acceptance-20261023/错因补讲完成与再练续接验收.html)

最终命令与指纹：`build/repair-readiness-final-20261023/command.json`。两端记录：`build/{UI.name}/ui-report.json`。本次未重复发出关机请求。
'''
    (ROOT/'docs'/('错因补讲完成与再练续接验收.md')).write_text(documentation,encoding='utf-8')
    status=ROOT/'docs/当前功能状态与待验收清单.md';current=status.read_text(encoding='utf-8')
    entry=f'2026-10-23 完成 [错因补讲完成与再练续接](错因补讲完成与再练续接验收.md)：详细批改尚未完成不退回只按分数出题；项目恢复后的保留取消批改可明确续接，原问卷先等填写，已评分步骤复用。普通练习页显示所有失分题的暂定卡点与默认复习选项，满分不显示错因再练，手机旧状态不绕过入口。最终{total}项关联回归、5项实际电脑／配对HTTPS交互及5项Node语法检查通过，8个生产文件指纹一致；受控调用5次（2评分、3分析含1取消），真实云调用0，原提交1份、95分保留，没有新练习任务。两份原生DOCX压缩包／正文与下载核对通过；不作真实模型质量、实体安卓、Word分页或整体性能认证。指南与手机壳v73同步，源码未打包。\n\n'
    if '[错因补讲完成与再练续接]' not in current:
        status.write_text(current.replace('## 已有实现及验收记录\n\n','## 已有实现及验收记录\n\n'+entry,1),encoding='utf-8')
    print(json.dumps({'report':str(OUT/(TITLE+'.html')),'tests':total,'artifacts':len(artifacts)},ensure_ascii=False))


if __name__=='__main__':main()
