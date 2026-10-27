"""Package completed native UI and regression evidence into an openable report."""
import hashlib
import html
import json
from pathlib import Path
import shutil
import sqlite3
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/'build/practice-hints-ui-20261023-3'
GATE=ROOT/'build/practice-hints-final-20261023'
OUT=ROOT/'build/practice-hints-acceptance-20261023-2'
TITLE='逐层思考提示与作答条件验收'


def main():
    gate=json.loads((GATE/'command.json').read_text(encoding='utf-8'))
    ui=json.loads((UI/'ui-report.json').read_text(encoding='utf-8'))
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    if OUT.exists():raise SystemExit('Use a fresh report folder; preserve earlier evidence.')
    OUT.mkdir()
    with sqlite3.connect(UI/'data/studyforge.sqlite3') as db:
        row=db.execute('SELECT path FROM artifacts WHERE id=?',(ui['feedback_artifact_id'],)).fetchone()
        assert row
        original=Path(row[0])
        assert original.is_file()
        sample=OUT/'逐层提示后的批改示例.docx'
        shutil.copy2(original,sample)
    with ZipFile(sample) as archive:
        assert archive.testzip() is None
        xml=ET.fromstring(archive.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paragraphs=[''.join(p.itertext()) for p in xml.findall('.//w:p',ns)]
    text='\n'.join(paragraphs)
    assert '本软件记录请求过第3层通用思考提示' in text
    assert '本软件没有记录本题的提示请求' in text
    assert '不因此改动本题原评分' in text
    (OUT/'批改示例正文.txt').write_text(text,encoding='utf-8')
    red=ET.parse(ROOT/'build/practice-hints-red-20261023-2.xml').getroot().findall('.//testcase')
    manifest={'title':TITLE,'tests':gate['tests'],'production_files':len(gate['production_before']),
        'source_frozen':gate['source_frozen'],'ui_checks':len(ui['checks']),
        'valid_red_baseline_failures':sum(c.find('failure') is not None for c in red),
        'controlled_grading_calls':ui['controlled_grading_calls'],'real_model_requests':0,
        'sample':{'name':sample.name,'sha256':hashlib.sha256(sample.read_bytes()).hexdigest(),
            'zip_ok':True,'text_checked':True,'word_pagination_checked':False},
        'physical_android':False,'packaged_exe':False}
    (OUT/'report.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    checks=['工作台每道普通题可展开提示；打开面板、切换方向均不写使用记录、不请求模型。',
        '逐层展开并回看前一层，草稿保留；未提交时不评分、不更新掌握分、不返回私有解析。',
        '关闭再打开工作台提交窗口，已用最高层级和作答草稿保留。',
        '已配对HTTPS手机沿用电脑记录，可继续请求下一层。',
        '320px深色手机尺寸下，提示控件不超出卡片宽度。',
        '手机完整提交后先交付参考解析；批改暂候期间请求提示被拒绝，原使用记录不改变。',
        '完成批改后保留提交前最高层和原评分；手机能下载实际生成的DOCX。',
        '再次打开已完成题单，不再提供提交前提示控件。']
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>逐层思考提示与作答条件验收</title><style>
:root{color-scheme:light;color:#233e35;background:#f0eee7;font:16px/1.85 "Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0}main{max-width:1100px;margin:auto;padding:30px 20px 65px}header,section{background:#fffdf8;border:1px solid #d9dfd6;border-radius:20px;padding:26px 30px;margin-bottom:20px}h1{font-size:31px;line-height:1.4}h2{font-size:23px}.eyebrow{font-size:13px;letter-spacing:.12em;color:#4d7868}.good,.note{border-radius:12px;padding:16px 20px}.good{background:#e8f3eb}.note{background:#fff0d8;border-left:4px solid #bc8a35}a{color:#116c58;text-underline-offset:3px}li{margin:8px 0}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #dce1d7;text-align:left;vertical-align:top}img{max-width:100%;display:block;border:1px solid #dce1d7;border-radius:14px;margin:15px 0}.phone{max-width:320px;margin:auto}details{border:1px solid #dce1d7;border-radius:14px;padding:14px 18px;margin:15px 0}summary{font-weight:650;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f3ed;padding:18px;border-radius:12px;font:14px/1.9 "Microsoft YaHei",sans-serif}@media(max-width:650px){main{padding:14px 9px}header,section{padding:20px 16px}h1{font-size:25px}table{font-size:14px}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-23 · SOURCE ACCEPTANCE</div>
<h1>卡住时给一点方向，作答条件如实保留</h1><p>为学习工作台和手机端补齐按题逐层提示，堵住完整提交到批改启动之间仍可追加提示的窗口，并在反馈文档中显示每题实际记录。</p>
<p><a href="../../验收最新版.vbs">最新版源码启动入口</a> · <a href="../../web/help/guide.html">软件内操作指南</a> · <a href="逐层提示后的批改示例.docx">批改示例DOCX</a></p>
<p>从Windows托盘彻底退出旧StudyForge，再在资源管理器双击“验收最新版.vbs”。本轮更新源码，未打包EXE。</p></header>
<section><h2>怎么用</h2><ol><li>进入学习工作台 → 提交作业，选择尚未提交的普通习题；手机在“作业与补讲”打开对应题单。</li><li>在某题答题框下展开“通用思考提示”。可选概念、前置、构造、方法、论证、计算，或还不确定卡点。</li><li>先看第一层，需要时再看下一层；前面已用的层可以回看。关掉窗口再回来仍有草稿与层级。</li><li>完整提交后立即查看参考解析；批改文档和按题回看会列出该题的软件提示记录及笔记自报。</li></ol>
<div class="good">打开面板与换方向不算使用；点击提示才记录。提示是固定通用的思考办法，不读取私有参考解、不调用模型，不代表已经理解或独立完成，也不因此直接扣分。</div>
<p class="note">这是普通习题的轻量入口，尚不按本题内容生成定制线索。编程作业仍使用现有提交与运行验证方式。</p></section>
<section><h2>提交边界的实际修复</h2><table><tr><th>情形</th><th>修复前</th><th>现在</th></tr>
<tr><td>工作台／手机需要提示</td><td>提示只在电脑“练习与作业”页</td><td>作答所在窗口逐题展开；原练习页保留</td></tr>
<tr><td>完整提交已被接受，批改尚未取得运行锁</td><td>可能仍接受提示请求，改变稍后批改读取的使用层级</td><td>检查持久提交记录后拒绝；记录写入与提交由数据库顺序确定</td></tr>
<tr><td>批改失败、取消或暂停等待错因</td><td>部分状态仍留有后加提示的窗口</td><td>该题单已有完整提交时保持边界；可看已交付解析或续接批改</td></tr>
<tr><td>阅读批改结果</td><td>Word逐题正文未明确展示提示条件</td><td>显示最高提示层与笔记自报；没有记录不等于没有其他帮助</td></tr></table>
<p>旧交付文件不自动重写。旧批改数据若没有作答条件，不补造“未用提示”；内部按题工具缓存版本更新为3，不删除聊天记录。</p></section>
<section><h2>实际界面</h2><img src="../practice-hints-ui-20261023-3/desktop-hint.png" alt="电脑工作台答题草稿、提示方向、下一层及回看按钮">
<details><summary>展开320px深色手机截图</summary><img class="phone" src="../practice-hints-ui-20261023-3/phone-hint-320-dark.png" alt="窄屏深色手机里的逐层提示控件"></details></section>
<section><h2>批改文档实际正文</h2><p>下面来自完整提交后的原生DOCX导出。题目、作答、100分评分和模型响应均为隔离测试数据；用于确认交付内容和记录，不评价模型教学能力。</p>
<p><a href="逐层提示后的批改示例.docx">下载DOCX</a> · <a href="批改示例正文.txt">纯文本核对</a></p><details><summary>展开完整正文</summary><pre>__TEXT__</pre></details></section>
<section><h2>验证记录</h2><p>最终__COUNT__项关联回归全部通过，失败、错误和跳过均为0；__FILES__个生产文件测试前后指纹一致。新增9项针对性检查覆盖8种持久提交状态和原生入队／解析交付／批改流程。</p>
<p>有效修复前基线8项失败，原因均为提交后仍接受提示。最初一次测试夹具违反外键、另一条等待到旧锁已启动，属于无效基线，独立保留；后续一条期望适应性状态却用了严格模式默认值，也已明确修正测试设置，未修改产品的模式政策。前两次UI流程通过，但导出样例采用的旧测试桩固定评语与100分冲突；最终换成明确的验收桩评语重跑通过，未修改生产评分逻辑，前次记录保留。</p>
<ol>__CHECKS__</ol><p>最终实际UI检查__UI__项，控制台错误0；受控批改请求2次，真实云模型调用0次。4个相关JavaScript文件通过Node语法检查。指南已同步，手机静态壳升级v70。</p>
<p><a href="../practice-hints-final-20261023/command.json">最终命令和源码指纹</a> · <a href="../practice-hints-final-20261023/regression.xml">回归XML</a> · <a href="../practice-hints-ui-20261023-3/ui-report.json">电脑与配对手机操作记录</a> · <a href="../practice-hints-red-20261023-2.xml">有效修复前失败记录</a> · <a href="report.json">验收摘要及样例指纹</a></p>
<p class="note">本轮没有新增长视频、真实模型讲解质量或全软件内存性能试验。手机使用实际HTTPS配对网关和浏览器尺寸，未在实体安卓重新验收。DOCX压缩包及正文已核对，没有认证Microsoft Word分页效果。提示不请求模型，但不能据此宣称整项AI任务提速。</p></section></main></html>'''
    page=page.replace('__TEXT__',html.escape(text)).replace('__CHECKS__',''.join('<li>'+html.escape(item)+'</li>' for item in checks))
    page=page.replace('__COUNT__',str(gate['tests']['total'])).replace('__FILES__',str(len(gate['production_before']))).replace('__UI__',str(len(ui['checks'])))
    (OUT/(TITLE+'.html')).write_text(page,encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
