"""Openable recovery-flow acceptance from final frozen-source evidence."""
import hashlib
import html
import json
from pathlib import Path
import shutil
import sqlite3
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/recovery-policy-acceptance-20261023'
GATE=ROOT/'build/recovery-policy-final-20261023-2'
UI=ROOT/'build/recovery-policy-ui-20261023-2'
TITLE='低分流程一致性与作答草稿验收'


def main():
    gate=json.loads((GATE/'command.json').read_text(encoding='utf-8'))
    ui=json.loads((UI/'ui-report.json').read_text(encoding='utf-8'))
    assert gate['source_frozen'] and gate['exit_code']==0 and ui['passed']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    if OUT.exists():raise SystemExit('Preserve earlier acceptance evidence; use a fresh folder.')
    OUT.mkdir();samples=[];bodies=[]
    with sqlite3.connect(UI/'data/studyforge.sqlite3') as db:
        db.row_factory=sqlite3.Row
        for mode,label,status in [('adaptive','自主修复','repair_required'),('strict','费曼流程','feynman_required')]:
            row=db.execute('SELECT a.options_json,a.grade_json,a.feedback_artifact_id,e.status FROM homework_attempts a '
                'JOIN exercise_sets e ON e.id=a.exercise_set_id WHERE a.exercise_set_id=?',(ui['exercise_ids'][mode],)).fetchone()
            assert row['status']==status
            assert json.loads(row['options_json'])['recovery_mode']==json.loads(row['grade_json'])['recovery_mode']==mode
            assert json.loads(row['grade_json'])['score']==79
            source=Path(db.execute('SELECT path FROM artifacts WHERE id=?',(row['feedback_artifact_id'],)).fetchone()[0])
            target=OUT/(label+'批改示例.docx');shutil.copy2(source,target)
            with ZipFile(target) as archive:
                assert archive.testzip() is None
                xml=ET.fromstring(archive.read('word/document.xml'))
                text='\n'.join(''.join(p.itertext()) for p in xml.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
            assert '79.0/100' in text and '2+3=4' in text
            samples.append({'mode':mode,'state':status,'score':79,'file':target.name,
                'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'zip_ok':True,'text_checked':True})
            bodies.append('<details><summary>'+label+' · 完整合成批改正文</summary><pre>'+html.escape(text)+'</pre></details>')
    report={'tests':gate['tests'],'production_files':len(gate['production_before']),'source_frozen':True,
        'ui_checks':len(ui['checks']),'controlled_model_calls':ui['controlled_model_calls'],
        'real_model_requests':0,'samples':samples,'physical_android':False,'word_pagination_checked':False,'packaged_exe':False}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    checks=['电脑沿用题单默认策略；修改后关闭再打开，选项与草稿恢复。',
        '来回切换两份题单，各自的答案与策略不串位；加载过程不会将空内容覆盖草稿。',
        '配对手机默认值与题单一致，可选择策略；刷新后恢复策略、笔记自报和作答，未请求模型。',
        '电脑与手机显示本次已接受的策略；诊断未结束时不提前开放后续费曼任务。',
        '自主修复79分：显示同难度再练，自愿讲解默认收起，没有自动发起后续任务。',
        '手机选择原有流程，同样79分：显示待完成讲解表单，不直接提供同难度再练。',
        '保存的选项、批改结果和实际题单状态一致；两份成绩均为79，没有自动新增题单。',
        '编程作业隐藏普通题的低分选项，继续使用原提交入口。']
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>低分流程一致性与作答草稿验收</title><style>
:root{color-scheme:light;color:#233e35;background:#f0eee7;font:16px/1.85 "Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:30px 20px 65px}header,section{background:#fffdf8;border:1px solid #d9dfd6;border-radius:20px;padding:26px 30px;margin-bottom:20px}h1{font-size:31px;line-height:1.4}h2{font-size:23px}.eyebrow{font-size:13px;letter-spacing:.12em;color:#4d7868}.good,.note{border-radius:12px;padding:16px 20px}.good{background:#e8f3eb}.note{background:#fff0d8;border-left:4px solid #bc8a35}a{color:#116c58;text-underline-offset:3px}li{margin:8px 0}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #dce1d7;text-align:left;vertical-align:top}img{max-width:100%;display:block;border:1px solid #dce1d7;border-radius:14px;margin:15px auto}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:20px}.phone{max-width:390px}details{border:1px solid #dce1d7;border-radius:14px;padding:14px 18px;margin:15px 0}summary{font-weight:650;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f3ed;padding:18px;border-radius:12px;font:14px/1.9 "Microsoft YaHei",sans-serif}@media(max-width:650px){main{padding:14px 9px}header,section{padding:20px 16px}h1{font-size:25px}.comparison{grid-template-columns:1fr}table{font-size:14px}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-23 · SOURCE ACCEPTANCE</div>
<h1>低分后怎么学，选择要真正生效</h1><p>补齐手机的低分处理选择，提交时固定本次流程，修复快速重开及切换题单的草稿归属。</p>
<p><a href="../../验收最新版.vbs">最新版源码启动入口</a> · <a href="../../web/help/guide.html">软件内指南</a> · <a href="report.json">本轮验证摘要</a></p><p>先从Windows托盘彻底退出旧StudyForge，再在资源管理器双击“验收最新版.vbs”。本轮更新源码，未打包EXE。</p></header>
<section><h2>怎么使用</h2><ol><li>工作台“提交作业”或手机作业页，打开尚未提交的普通题单。</li><li>展开“作答条件与低分处理”，沿用题单默认值，或为本次作答选择处理方式。</li><li>完整提交后，电脑和手机的结果中均会显示本次采用的流程。策略在接受提交时保存，不随之后的默认设置改变。</li></ol>
<table><tr><th>选择</th><th>低于80分后的实际流程</th></tr><tr><td>先诊断，自主选择修复</td><td>完成批改与错因补讲后，可按需同难度再练；自愿讲解默认收起，没有强制进阶。</td></tr><tr><td>原有费曼讲解与进阶</td><td>显示待完成的讲解表单，先完成费曼环节，再按原有条件进入进阶。</td></tr></table>
<div class="good">两种选择采用相同评分标准和80分通过线。本轮用完全相同的作答与固定79分做流程对照：自主修复保存为repair_required，原有流程保存为feynman_required。</div><p>错因尚待确认或补讲未结束时，手机先等待原反馈，不抢先开放后续讲解任务。编程题继续使用代码提交与运行验证。</p></section>
<section><h2>实际界面对照</h2><p>两张均为实际配对HTTPS页面：左侧390px，右侧320px深色尺寸；用于核对控件和流程，没有在实体安卓重新操作。</p><div class="comparison"><div><h3>自主修复 · 79分</h3><img class="phone" src="../recovery-policy-ui-20261023-2/phone-adaptive-optional.png" alt="自主修复下的同难度再练入口和默认收起的可选讲解"></div><div><h3>原有费曼流程 · 79分</h3><img class="phone" src="../recovery-policy-ui-20261023-2/phone-strict-required-320-dark.png" alt="原有流程下展开的待完成费曼讲解表单"></div></div></section>
<section><h2>两处数据问题</h2><h3>排队期间的默认值漂移</h3><p>旧版在后台真正开始批改时才读取题单默认值；提交未显式传入策略时，排队期间的修改可能让本次流程切换。现在新提交在入队前保存有效策略，稍后批改和重试沿用该值。已有历史记录若没有有效策略，不猜造它原先的选择。</p>
<h3>关闭事件覆盖及草稿串位</h3><p>实测发现快速关闭再打开时，延迟关闭事件可把加载中的空内容覆盖原草稿。题单选择变化后，旧输入也可能以新选择的ID保存。现在以实际渲染的项目／对话／题单作为草稿归属，加载状态不保存；切换前先保留旧题单输入，再绘制新题单。</p></section>
<section><h2>验证记录</h2><p>最终__COUNT__项关联回归全部通过，失败、错误、跳过均0；__FILES__个生产文件测试前后指纹一致。4项新原生提交测试覆盖两种默认策略在排队中被改动、以及显式选择覆盖默认值；修复前4项失败的记录保留，其中两项实际复现低分分支反转。</p><ol>__CHECKS__</ol>
<p>最终实际UI__UI__项通过，控制台错误0。受控模型请求__CALLS__次（两份评分各两次核对及一次补讲），真实云模型请求0次。3个相关JavaScript文件语法检查通过，手机静态壳升级v71，指南已同步。</p>
<p><a href="../recovery-policy-final-20261023-2/command.json">最终命令与源码指纹</a> · <a href="../recovery-policy-final-20261023-2/regression.xml">最终回归XML</a> · <a href="../recovery-policy-ui-20261023-2/ui-report.json">实际UI操作记录</a> · <a href="../recovery-policy-red-20261023-2.xml">修复前失败记录</a></p>
<details><summary>中途问题与证据边界</summary><p>第一轮UI实际发现草稿覆盖，失败记录和截图保留。第一次关联回归198项本身通过，但执行期间为修复该问题修改了源码，指纹检查拒绝将其当作最终验收；最终对固定源码重新通过。</p><p>本轮验证处理流程、草稿和实际交付，不是模型评分准确性、讲解质量、全软件内存或长任务提速试验。固定79分由测试桩提供，没有更换生产模型或提高提示词强度。DOCX压缩包及正文核对不证明Microsoft Word分页效果。</p></details></section>
<section><h2>原生批改导出</h2><p>下面两份来自上述完整提交，供查看合成批改及作答条件；它们的区别是对应的后续学习流程，不代表两种教学效果的比较。</p><p><a href="自主修复批改示例.docx">自主修复批改示例</a> · <a href="费曼流程批改示例.docx">费曼流程批改示例</a></p>__BODIES__</section></main></html>'''
    page=page.replace('__COUNT__',str(gate['tests']['total'])).replace('__FILES__',str(report['production_files']))
    page=page.replace('__UI__',str(report['ui_checks'])).replace('__CALLS__',str(report['controlled_model_calls']))
    page=page.replace('__CHECKS__',''.join('<li>'+html.escape(check)+'</li>' for check in checks)).replace('__BODIES__',''.join(bodies))
    (OUT/(TITLE+'.html')).write_text(page,encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
