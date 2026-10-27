"""Acceptance for readable formula passages and exact source quotation."""
from pathlib import Path
import json
import shutil
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/message-math-acceptance-20261025'
UI=ROOT/'build/message-math-ui-20261025-3'
GATE=ROOT/'build/message-math-final-20261025'
TITLE='原句追问公式与Markdown显示验收'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate=load(GATE/'command.json');ui=load(UI/'ui-report.json');mapping=load(UI/'source-mapping-checks.json');case=load(UI/'case.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and len(gate['production_before'])==9
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert ui['passed'] and len(ui['checks'])==9 and ui['controlled_model_requests']==3 and not ui['console_errors']
    assert mapping['passed'] and len(mapping['cases'])==24 and 4000<len(case['math_text'])<=7000
    db=sqlite3.connect('file:'+str(UI/'data/studyforge.sqlite3')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    references=[dict(row) for row in db.execute('SELECT reference_json FROM message_focus_references')]
    assert len(references)==3
    selected=[json.loads(row['reference_json']) for row in references]
    assert selected[-1]['selection']['text']==case['math_quote']
    assert db.execute('SELECT COUNT(*) FROM mastery').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM learning_insights').fetchone()[0]==0
    db.close()
    if OUT.exists():raise SystemExit('Preserve earlier acceptance files.')
    OUT.mkdir()
    before=Path('C:/Users/Lenovo/AppData/Local/Temp/codex-clipboard-35ba55b6-8b50-4302-90e9-3195b3ceb959.png')
    if before.is_file():shutil.copy2(before,OUT/'用户反馈的原界面.png')
    report={'date':'2026-10-25','gate':gate,'ui':ui,'mapping':mapping,
        'synthetic_reply_characters':len(case['math_text']),'saved_reference_count':3,
        'packaged':False,'limits':['no physical Android long-press test','no model-quality certification',
            'complex unmappable syntax uses exact source mode','long answers retain bounded paging']}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    total=gate['tests']['total']
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>原句追问公式与Markdown显示验收</title><style>
:root{color:#233f35;background:#eeeee8;font:16px/1.85 "Microsoft YaHei",sans-serif;color-scheme:light}*{box-sizing:border-box}body{margin:0}main{max-width:1100px;margin:auto;padding:28px 20px 65px}header,section{background:#fffef9;border:1px solid #d8dfd5;border-radius:20px;padding:25px 30px;margin-bottom:20px}h1{font-size:30px;line-height:1.4}h2{font-size:23px}a{color:#126c58;text-underline-offset:3px}.eyebrow{font-size:13px;letter-spacing:.1em;color:#52796a}.note{padding:16px 20px;background:#fff0da;border-left:4px solid #c28b34;border-radius:12px}li{margin:9px 0}img{display:block;max-width:100%;border:1px solid #d7dfd6;border-radius:14px;margin:16px auto}.phone{max-width:320px}details{border:1px solid #dce2d8;border-radius:14px;padding:15px 18px;margin:16px 0}summary{font-weight:650;cursor:pointer}code{background:#edf1ea;padding:2px 5px;border-radius:5px}@media(max-width:650px){main{padding:14px 9px}header,section{padding:20px 16px}h1{font-size:25px}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-25</div><h1>选原句时，也能正常阅读公式</h1><p>“针对导师原句追问”原先使用纯文本框，直接显示 Markdown 和 LaTeX 标记。现在默认渲染标题、列表、强调、行内公式与独立公式，同时保留准确引用原文的能力。</p><p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../web/help/guide.html#tutor">软件内指南</a> · <a href="report.json">验收摘要</a></p><p>先从 Windows 托盘彻底退出旧 StudyForge，再双击“验收最新版.vbs”；手机连接后刷新。本轮未重新打包安装版。</p></header>
<section><h2>现在怎样使用</h2><ol><li>点击导师回答下的“针对这段追问”，默认打开<strong>阅读 · 公式排版</strong>。可以直接阅读并拖选原句。</li><li>选中公式的任意部分时，引用完整的原始公式；代码同样保留完整内容，避免只截到分子、下标或半段代码。</li><li>需要核对记号、选择部分代码或复杂格式时，切换<strong>原文 · Markdown</strong>，原有精确选段仍保留。</li><li>点击“使用选中原句”后，输入框上方的引用预览也显示公式；发送后保存的引用快照同样正常排版。</li></ol><p>不超过 7000 字符的回答完整显示，避免用户截图中的四千多字回答在 4000 字符处被截断。更长回答仍按窗口读取，保留翻页和按字符跳转。窗口更宽，阅读区可拉高或缩短。</p><img src="../message-math-ui-20261025-3/电脑端公式阅读与选择.png" alt="电脑端原句追问默认显示正常的行列式与代数余子式公式"><details><summary>查看用户反馈的修改前界面</summary><img src="用户反馈的原界面.png" alt="修改前的窗口直接显示Markdown和LaTeX记号"></details><details><summary>320px 深色手机界面</summary><img class="phone" src="../message-math-ui-20261025-3/手机端正常公式阅读.png" alt="配对手机使用相同公式阅读视图和原文切换"></details></section>
<section><h2>排版没有改变引用依据</h2><p>显示可以去掉排版记号，发送给导师的仍是保存回答中的精确原文与原坐标。文字重复出现时按所在位置引用，不搜索并套用第一处同名句子。中文、数学字符、emoji、换行及实体编码均核对原文；公式按整体保留 LaTeX。服务器继续核对内容指纹、原句和所属项目／对话。</p><p>查看和选择只在本机完成，没有新增模型请求、文件解析或学习评分。旧 AI 回答仍可能有错，引用它不代表学生认可或掌握，也不替代教材证据。</p><p class="note">部分复杂格式（例如表格中的精细选段）若无法准确映射，会提示切换原文选择，不猜引用位置。格式本身仍可阅读。任意位置跳转的长回答可能从公式中间开始，需回到更早片段或原文核对；损坏公式也不会被自动补写成另一条公式。</p></section>
<section><h2>验证结果</h2><p>最终 __TOTAL__ 项关联回归全部通过，失败、错误、跳过均 0；9 个生产文件前后指纹一致。5 项 JavaScript 语法检查通过，指南与手机壳 v78 同步。</p><p>真实浏览器内 24 项原文映射检查通过：重复句、粗体、标题、Unicode、CRLF、HTML 实体、转义符、链接同名词、引用段、多级列表、行内／整块代码、四类公式定界符、跨强调选段、复杂格式回退、无效脚本及 3000 原文字符限制。</p><p>9 组电脑／配对 HTTPS 手机流程通过，控制台错误 0。以 __LENGTH__ 字符的合成数学回答实际核对跨 4000 字符后的完整显示；选中渲染后公式的一小部分，原生聊天请求收到完整原始 LaTeX。原引用草稿隔离、重开恢复、历史快照和手机切换也通过。共 3 次受控导师请求，外部模型请求 0；保存引用 3 条，画像分数与学习洞察均未因引用增加。</p><p><a href="../message-math-final-20261025/command.json">最终命令与指纹</a> · <a href="../message-math-final-20261025/regression.xml">回归 XML</a> · <a href="../message-math-ui-20261025-3/ui-report.json">两端操作记录</a> · <a href="../message-math-ui-20261025-3/source-mapping-checks.json">24 项映射记录</a></p><details><summary>过程中的问题</summary><p>第一轮在转义符用例发现：解析器把 escape 交给 text 渲染器，导致原文反斜杠显示或引用范围不对。现已按完整原始转义处理，所有用例通过。第二轮完整流程通过后，扩大合成回答到 4000 字符以上重新验收，避免把短文本试验误当成分页合并证据。最终固定源码重跑关联回归。</p></details><p>手机验收使用真实 HTTPS 配对与手机尺寸窗口，未实测实体安卓的长按手势；本轮不评价真实模型教学质量或全软件性能，没有调用模型重新生成旧回答。</p></section></main></html>'''
    (OUT/(TITLE+'.html')).write_text(page.replace('__TOTAL__',str(total)).replace('__LENGTH__',str(len(case['math_text']))),encoding='utf-8')
    doc=f'''# 原句追问公式与Markdown显示验收

2026-10-25，源码更新，未打包。

- 原句追问默认正常渲染 Markdown 与 KaTeX 公式，保留“原文 · Markdown”切换；窗口加宽、阅读区可调整高度，电脑和手机共用。
- 可在排版正文中选段，公式和代码按完整原始内容引用；重复句、Unicode、CRLF 与实体编码映射到原坐标，复杂格式无法精确映射时明确切回原文，不猜位置。服务器指纹与所属对话核对保持。
- 7000字符以内的回答合并已保存窗口完整显示，特长回答仍分页。引用预览及发送后快照同样支持公式；查看、选择不调用AI、不解析资料、不增加掌握分。
- 最终{total}项关联回归通过，失败／错误／跳过均0，9个生产文件指纹一致；5项JS语法检查通过，24项真实浏览器映射检查与9组两端流程通过，控制台错误0。
- {len(case['math_text'])}字符的合成数学回答核对4000字符后的完整显示；公式局部选择在实际导师请求中保留完整LaTeX。受控3请求、外部模型0；引用3条，画像分数／洞察均0。
- 首轮转义符范围问题已修复；短样例扩大到4000字符以上重新验证。手机为配对HTTPS尺寸窗口，不认证实体安卓长按、模型教学或整体性能。指南与手机壳v78同步。

验收页：[原句追问公式与Markdown显示验收.html](C:/Users/Lenovo/Documents/ChatGPT/codex workspace/build/message-math-acceptance-20261025/原句追问公式与Markdown显示验收.html)

先托盘彻底退出旧StudyForge，再双击“验收最新版.vbs”；手机连接后刷新。未打包，未新增关机动作。
'''
    (ROOT/'docs/原句追问公式与Markdown显示验收.md').write_text(doc,encoding='utf-8')
    path=ROOT/'docs/当前功能状态与待验收清单.md';text=path.read_text(encoding='utf-8')
    entry=f'2026-10-25 完成 [原句追问公式与Markdown显示](原句追问公式与Markdown显示验收.md)：默认正常正文与公式，保留原文切换及精确引用；公式／代码整体保留原始内容，重复句和Unicode坐标核对，复杂格式不猜位置。7000字符内完整显示，引用预览和历史快照同步渲染。最终{total}项关联回归、24项浏览器映射及9组两端流程通过，9个生产文件指纹一致；受控3请求、外部0，画像分数／洞察不增加。指南和手机壳v78，源码未打包；未认证实体安卓长按、模型质量或整体性能。\n\n'
    if '[原句追问公式与Markdown显示]' not in text:path.write_text(text.replace('## 已有实现及验收记录\n\n','## 已有实现及验收记录\n\n'+entry,1),encoding='utf-8')
    print(json.dumps({'report':str(OUT/(TITLE+'.html')),'tests':total,'ui_checks':len(ui['checks']),'source_mapping_cases':len(mapping['cases'])},ensure_ascii=False))


if __name__=='__main__':main()
