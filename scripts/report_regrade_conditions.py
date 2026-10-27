"""Save verified evidence before the user's requested shutdown."""
import hashlib
import html
import json
from pathlib import Path
import shutil
import sqlite3
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/'build/regrade-conditions-ui-20261023-1'
GATE=ROOT/'build/regrade-conditions-final-20261023'
OUT=ROOT/'build/regrade-conditions-acceptance-20261023'
TITLE='评分复核原始作答条件与画像验收'


def main():
    gate=json.loads((GATE/'command.json').read_text(encoding='utf-8'))
    ui=json.loads((UI/'ui-report.json').read_text(encoding='utf-8'))
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    if OUT.exists():raise SystemExit('Preserve earlier evidence; use a fresh report folder.')
    OUT.mkdir();samples=[];texts=[]
    with sqlite3.connect(UI/'data/studyforge.sqlite3') as db:
        db.row_factory=sqlite3.Row
        for key,label in [('supported','参考过笔记的复核示例'),('partial','旧条件不完整的复核示例')]:
            item=ui['items'][key]
            row=db.execute('SELECT s.id,s.grade_json,a.feedback_artifact_id FROM submissions s JOIN homework_attempts a '
                'ON a.exercise_set_id=s.exercise_set_id WHERE a.id=?',(item['attempt_id'],)).fetchone()
            grade=json.loads(row['grade_json']);assert row['id']==item['submission_id']
            assert grade['score']==100 and grade['regrade_basis']['same_answers'] is True
            assert grade['practice_context']['used_notes'] is (key=='supported')
            source=Path(db.execute('SELECT path FROM artifacts WHERE id=?',(row['feedback_artifact_id'],)).fetchone()[0])
            target=OUT/(label+'.docx');shutil.copy2(source,target)
            with ZipFile(target) as archive:
                assert archive.testzip() is None
                root=ET.fromstring(archive.read('word/document.xml'))
                text='\n'.join(''.join(p.itertext()) for p in root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
            assert '评分复核' in text and '原作答' in text and '100.0/100' in text
            assert ('参考过笔记' if key=='supported' else '仅部分保存') in text
            samples.append({'file':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                'same_submission':True,'practice_context':grade['practice_context'],'regrade_basis':grade['regrade_basis'],
                'zip_ok':True,'text_checked':True})
            texts.append('<details><summary>'+label+' · 原生DOCX全文</summary><pre>'+html.escape(text)+'</pre></details>')
    manifest={'tests':gate['tests'],'source_frozen':True,'production_files':len(gate['production_before']),
        'ui_checks':len(ui['checks']),'controlled_model_calls':ui['controlled_model_calls'],'real_model_requests':0,
        'samples':samples,'physical_android':False,'word_pagination_checked':False,'packaged_exe':False,
        'requested_shutdown':True,'shutdown_state':'not_yet_requested'}
    (OUT/'report.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    checks=['电脑在作业历史点击重新复核，保留原笔记自报和自主修复策略，历史显示复核标记。',
        '原生逐题阅读器与已交付内容注明评分复核，保留参考过笔记的记录。',
        '配对HTTPS手机能复核旧条件不完整的已提交作业，并显示原作答复核提示。',
        '两份成绩各一次更新为100分；总提交仍为2份、做题证据仍为2条，均未计入未借助帮助的参考分。',
        '320px深色手机阅读器显示旧条件缺失；两份实际批改DOCX均可下载，查看与下载不新增模型请求。']
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>评分复核原始作答条件与画像验收</title><style>
:root{color-scheme:light;color:#233e35;background:#f0eee7;font:16px/1.85 "Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:30px 20px 65px}header,section{background:#fffdf8;border:1px solid #d9dfd6;border-radius:20px;padding:26px 30px;margin-bottom:20px}h1{font-size:30px;line-height:1.4}h2{font-size:23px}.eyebrow{font-size:13px;letter-spacing:.12em;color:#4d7868}.good,.note{border-radius:12px;padding:16px 20px}.good{background:#e8f3eb}.note{background:#fff0d8;border-left:4px solid #bc8a35}a{color:#116c58;text-underline-offset:3px}li{margin:8px 0}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #dce1d7;text-align:left;vertical-align:top}img{max-width:100%;display:block;border:1px solid #dce1d7;border-radius:14px;margin:15px auto}.phone{max-width:320px}details{border:1px solid #dce1d7;border-radius:14px;padding:14px 18px;margin:15px 0}summary{font-weight:650;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f3ed;padding:18px;border-radius:12px;font:14px/1.9 "Microsoft YaHei",sans-serif}@media(max-width:650px){main{padding:14px 9px}header,section{padding:20px 16px}h1{font-size:25px}table{font-size:14px}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-23 · SOURCE ACCEPTANCE</div><h1>重新核对分数，保留同一次作答的事实</h1>
<p>修复评分复核丢失原笔记自报、重新选择低分策略，以及旧条件缺失时补认“没有帮助”的问题。</p><p><a href="../../验收最新版.vbs">最新版源码启动入口</a> · <a href="../../web/help/guide.html">软件内指南</a> · <a href="report.json">验收摘要与Word指纹</a></p><p>从Windows托盘彻底退出旧StudyForge，再在资源管理器双击“验收最新版.vbs”。本轮源码更新，未打包EXE。</p></header>
<section><h2>为什么影响后续教学</h2><p>导师需要区分“参考资料后会做”和“自报未查笔记、未使用软件提示时会做”。旧版重新复核评分时重新采集当前作答条件，原先的true／false自报可能变成未说明；直接传新值还可能把参考过笔记改成未使用。原默认流程也可能在复核时改变。</p>
<table><tr><th>原始条件</th><th>现在复核的处理</th></tr><tr><td>参考过笔记</td><td>保留原true自报；自主流程高分仍标为借助支持达到通过线，不计入未借助帮助的参考分。</td></tr><tr><td>未参考笔记／未说明</td><td>分别保留false／未知；不会因复核请求缺字段而重写，也不会因此证明独立完成。</td></tr><tr><td>旧记录只保存部分条件</td><td>保留已有字段，明确缺失部分未知，不把缺少提示记录当作没有使用提示。</td></tr><tr><td>旧记录完全缺少作答条件</td><td>不使用复核时的状态补造；不计入未借助帮助或延迟保持的参考证据。</td></tr><tr><td>低分处理方式</td><td>有原有效值就沿用原值；早期缺字段才使用现有回退方式，并标明它不是恢复出的原选择。</td></tr></table>
<div class="good">复核更新同一份提交，不增加一次练习。评分标准与核查轮次保持；本轮没有通过提示使用直接加分或扣分，也没有更换教师提示词。</div></section>
<section><h2>实际操作</h2><ol><li>电脑作业历史中，对“评分待核实”的记录点“重新复核原作答”；普通练习页保留相同复核入口。</li><li>手机打开对应作业，点“复核原评分”。完成后结果注明这是原作答的评分复核。</li><li>批改Word和按题回看同步说明原条件；历史记录不被当作第二次练习。</li></ol>
<img src="../regrade-conditions-ui-20261023-1/desktop-rechecked-conditions.png" alt="电脑实际复核后阅读器显示原作答复核说明"><details><summary>展开320px深色手机截图</summary><img class="phone" src="../regrade-conditions-ui-20261023-1/phone-partial-conditions-320-dark.png" alt="手机阅读原作答的评分复核记录"></details></section>
<section><h2>验证证据</h2><p>修复前6项针对性检查未通过，复现自报覆盖、处理策略变化和缺失条件补认，并检查原先没有复核标记。最终__COUNT__项关联回归全通过，失败、错误、跳过均0；__FILES__个生产文件在最终测试前后指纹一致，其中新针对性10项。中途39项聚焦检查已通过，各组重叠不相加。</p><ol>__CHECKS__</ol>
<p>实际电脑与配对HTTPS操作__UI__项通过，控制台错误0。原生复核共4次受控评分请求，真实云请求0次；初始待核实状态是合成种子，提交初次待核实和复核的原生逻辑另由针对性测试覆盖。4个相关JavaScript文件语法检查通过；指南与手机壳v72同步。</p>
<p><a href="../regrade-conditions-final-20261023/command.json">最终命令和源码指纹</a> · <a href="../regrade-conditions-final-20261023/regression.xml">最终回归XML</a> · <a href="../regrade-conditions-ui-20261023-1/ui-report.json">实际UI操作记录</a> · <a href="../regrade-conditions-red-20261023.xml">修复前针对性失败</a></p>
<p class="note">这是记录保真、画像依据和交付流程验证。固定100分由测试桩提供，不评价真实模型评分或讲解质量；未重新验收实体安卓、Word分页或全软件内存／长任务速度。</p></section>
<section><h2>原生批改文档</h2><p>下面两份均已完整提交并完成复核，使用合成资料，供核对原条件与复核说明。</p><p><a href="参考过笔记的复核示例.docx">参考过笔记的复核示例</a> · <a href="旧条件不完整的复核示例.docx">旧条件不完整的复核示例</a></p>__TEXTS__</section>
<section><h2>本次关机要求</h2><p>用户已要求完成后关机。先保存本页、源码、文档和测试证据，再启动一次正常关机请求；不强制结束未保存应用。实际请求记录在<a href="shutdown-status.json">shutdown-status.json</a>；该日志记录请求，不作为机器已经断电的证明。</p></section></main></html>'''
    page=page.replace('__COUNT__',str(gate['tests']['total'])).replace('__FILES__',str(manifest['production_files'])).replace('__UI__',str(manifest['ui_checks']))
    page=page.replace('__CHECKS__',''.join('<li>'+html.escape(check)+'</li>' for check in checks)).replace('__TEXTS__',''.join(texts))
    (OUT/(TITLE+'.html')).write_text(page,encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
