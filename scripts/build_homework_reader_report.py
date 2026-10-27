"""Build a local, openable acceptance page only from completed gate evidence."""
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote, unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/homework-reader-acceptance-20261022'
GATE=ROOT/'build/homework-reader-checked-20261022'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ui_folder=ROOT/'build'/sys.argv[1]
    gate=json.loads((GATE/'final-command.json').read_text(encoding='utf-8'))
    ui=json.loads((ui_folder/'ui-report.json').read_text(encoding='utf-8'))
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed']
    assert all(digest(ROOT/name)==value for name,value in gate['production_after'].items())
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert ui['controlled_model_requests']==0 and ui['external_model_requests']==0
    OUT.mkdir(exist_ok=True)
    def href(path):return quote(os.path.relpath(path,OUT).replace('\\','/'),safe='/')
    def link(path,label):return '<a href="'+href(path)+'">'+escape(label)+'</a>'
    def screen(filename,label):
        path=ui_folder/filename
        assert path.is_file()
        return '<figure><a href="'+href(path)+'"><img src="'+href(path)+'" alt="'+escape(label)+'"></a><figcaption>'+escape(label)+'</figcaption></figure>'
    pictures=screen('desktop-question-reader.png','电脑端：独立阅读窗口，题号切换与原作答对照')
    pictures+=screen('desktop-question-teaching.png','电脑端：向下滚动后的针对性讲解与核对方法')
    pictures+='<div class="phones">'+screen('phone-question-reader-390.png','配对 HTTPS 手机界面 · 390px')+screen('phone-question-teaching-390.png','手机滚动查看补讲与公式')+screen('phone-question-reader-320-dark.png','320px 深色界面，正文独立滚动')+'</div>'
    docs=list(ui_folder.rglob('homework-reader.docx'));assert len(docs)==1
    checks=''.join('<li>'+escape(text)+'</li>' for text in ui['checks'])
    tests=gate['tests']['total']
    files=[GATE/'final-command.json',GATE/'final-regression.xml',GATE/'final-regression.log',
           ui_folder/'ui-report.json',ui_folder/'server.log',ui_folder/'electron.log',docs[0]]
    evidence=''.join('<li>'+link(path,path.name)+'</li>' for path in files)
    style='''*{box-sizing:border-box}html{background:#edf2ec;color:#253d34;font:16px/1.85 system-ui,"Microsoft YaHei",sans-serif}body{max-width:1160px;margin:auto;padding:28px}header,section{background:#fffefa;border:1px solid #d8e4d9;border-radius:22px;padding:26px 30px;margin-bottom:20px}header{background:linear-gradient(120deg,#fffefa,#dfeee3)}h1{font-size:34px;line-height:1.5;margin:10px 0}h2{font-size:24px}h3{font-size:18px}.tag{font-size:12px;letter-spacing:2px;color:#42745d;font-weight:700}.stats{display:flex;gap:14px;flex-wrap:wrap}.stats div{background:#fffefa;border-radius:14px;border:1px solid #c9ddcc;padding:12px 20px}.stats strong{display:block;font-size:26px;color:#256447}a{color:#256447;text-underline-offset:4px}li{margin:9px 0}table{width:100%;border-collapse:collapse;display:block;overflow:auto}td,th{padding:12px;border:1px solid #d8e4d9;min-width:130px;text-align:left}th{background:#eef5ed}.notice{border-left:4px solid #bd8a3c;background:#fcf4e5;padding:14px 18px;border-radius:8px}figure{margin:24px 0}img{display:block;width:100%;height:auto;border-radius:14px;border:1px solid #d8e4d9}figcaption{font-size:13px;color:#526d5d;margin:8px 0}.phones{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.phones figure{min-width:0}.small{color:#536c5f;font-size:14px}@media(max-width:650px){body{padding:12px}header,section{padding:18px;border-radius:16px}h1{font-size:26px}.phones{grid-template-columns:1fr}.phones figure{max-width:390px;margin:auto}.stats div{flex:1;min-width:120px}}'''
    body=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>按题回看与原对话追问验收</title><style>{style}</style></head><body>
<header><div class="tag">STUDYFORGE · 2026-10-22 · 源码验收</div><h1>从整份文档下载，走到按题阅读和继续追问</h1><p>把原题、自己的作答、已交付解析和针对性补讲放在一个独立阅读窗口。读完某一道，再带题号返回原学习对话。</p><div class="stats"><div><strong>{tests}</strong>关联回归通过</div><div><strong>{len(ui['checks'])}</strong>实际两端界面检查</div><div><strong>0</strong>验收模型请求</div></div></header>
<section><h2>怎样打开</h2><ol><li>从系统托盘彻底退出旧版 StudyForge，双击 {link(ROOT/'验收最新版.vbs','验收最新版.vbs')}。</li><li>电脑学习工作台的“作业反馈”或作业历史记录中，找到已有解析或批改文档的题单，点击“按题回看”。手机在作业详情中使用同名按钮。</li><li>选择题号；长记录按“继续加载本题记录”展开。阅读不会向聊天中插入消息。</li><li>点“带题号回原对话”，补充自己的具体疑问，再发送。已有草稿保留，不自动提问。</li></ol><p>查看 {link(ROOT/'web/help/guide.html','软件内操作指南')}，第10节已补充该流程。手机壳版本 v67；本轮未打包 EXE。</p></section>
<section><h2>学习体验的实际变化</h2><table><thead><tr><th>环节</th><th>原先入口</th><th>本轮实现</th></tr></thead><tbody><tr><td>查看一道错题</td><td>主要下载整份 Word，再定位题号</td><td>独立窗口按题显示，不切割原聊天</td></tr><tr><td>结合自己的作答</td><td>需要来回寻找原作答与讲解</td><td>同一题内对照原题、作答、评分、错因、补讲和参考解</td></tr><tr><td>继续向导师提问</td><td>手动寻找原对话、说明题单与题号</td><td>返回原对话并带入题单名称、题号；草稿保留</td></tr><tr><td>长记录</td><td>可能整份加载</td><td>每次最多12000字符，按需继续；约14万字符预览上限，超出查看完整文档</td></tr><tr><td>评分疑点</td><td>逐题窗口可能带出整份题单未注明题号的疑点</td><td>只提示存在总体疑点，不把未归属的问题安到当前题上；完整文档继续保留全部疑点</td></tr></tbody></table></section>
<section><h2>真实界面截图</h2><p class="small">这是实际运行的软件页面与配对 HTTPS 手机页面。题目、评分和补讲是合成夹具；长记录有明确标注的重复滚动样例，截图不用于证明模型教学质量。</p>{pictures}</section>
<section><h2>验证记录</h2><p>{tests}项关联回归全部通过，失败、错误、跳过均为0；测试前后12个生产文件指纹一致。检查涵盖新读取接口、原导师工具隔离、原作业暂停／问卷／续做、上轮分题复用、手机访问与教学核查回归。逐题记录版本更新到2；单独核验旧内部工具状态会失效，公开消息保持不变。</p><ol>{checks}</ol><p>查看、切题、加载后续内容及返回输入框均为本机操作，不增加模型请求、评分、作业提交或学习画像。新的人类阅读接口允许用户显式查看本项目其他对话已交付的记录；AI工具仍只允许回看原学习对话，返回提问也回到原对话。</p><p class="notice">两端实测由隐藏 Electron 窗口与配对 HTTPS 网关完成，尚未替代实体安卓手机测试。本轮没有新的真实模型对照，不认证模型教学能力、全文事实正确性或整个软件性能。参考解与旧补讲仍可能有误；原评分为夹具指定值。</p></section>
<section><h2>边界与失败记录</h2><ul><li>尚未交付的私有错因不显示；没有完整作答或已交付记录时不公开参考答案。</li><li>题目变化、原对话删除、文件缺失或项目不对应时明确报错，不冒用其他记录。</li><li>长记录以版本指纹核对每个窗口；版本变化需要刷新，不把两版讲解拼起来。</li><li>同名题单仍可能需要补充题意；带题号操作只整理输入草稿，不直接把全文灌入对话。</li><li>第一次 Electron 在受限环境中启动失败；随后宿主窗口访问沙箱服务超时。统一到同一环境后，延迟请求夹具错误等待自身 Promise，后又把函数当作执行返回值而触发 IPC 克隆错误；两项均为验收脚本问题。修正后另起新目录重做，保留早期目录。</li></ul></section>
<section><h2>原始证据与文件</h2><ul>{evidence}</ul><p>{link(ROOT/'docs/按题回看与原对话追问验收.md','实现与验收说明')}</p></section>
</body></html>'''
    target=OUT/'按题回看与原对话追问验收.html';target.write_text(body,encoding='utf-8')
    manifest={'gate':gate,'ui':ui,'ui_folder':str(ui_folder),'files':{str(path.relative_to(ROOT)):digest(path) for path in files}}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    doc=ROOT/'docs/按题回看与原对话追问验收.md'
    doc.write_text(f'''# 按题回看与原对话追问验收\n\n2026-10-22，源码更新，未打包EXE。\n\n## 实现\n\n- 电脑作业反馈／历史记录与手机作业详情新增“按题回看”。独立窗口显示一题已交付记录，不在消息区插入笔记，不请求模型。\n- 复用原逐题渲染和交付校验，待错因时只开放已经发布的解析。人类用户可显式查看本项目作业，模型工具仍保持原对话隔离。\n- 每次最多12000字符、按需加载，版本指纹变化拒绝拼接；约14万字符预览上限，完整内容继续可下载。\n- “带题号回原对话”保留两侧草稿，预填题单／题号，不自动发送；同名题单仍须补充题意。\n- 全局未标题号的评分疑点不归因于单题，完整文档保留全部疑点。指南和手机壳v67同步。\n\n## 证据\n\n- 首批41项接口／隔离检查通过；补充总体疑点归属检查后，最终{tests}项关联回归全部通过，无失败、错误或跳过。12个生产文件指纹前后相同。\n- {len(ui['checks'])}项实际电脑与配对HTTPS界面检查通过，含长记录、切题、数学公式、迟到请求、原对话返回和两侧草稿保留，以及390／320px深色显示。\n- 界面验收0项模型请求；不新增评分或掌握度。未使用真实用户数据库。\n- 初次沙箱启动／跨环境连接失败单列；另一次人工延迟夹具误等自身Promise，修正脚本并在新目录重测。\n\n## 限制\n\n- 实际界面使用合成题目与人工给定分数，不是新的AI教学质量或评分准确性评测。\n- 未完成实体安卓、完整Word分页或全软件性能认证。\n- 早期作业题目改变或原对话已删除时，不借新状态重建历史，只提示查看原交付文档。\n\n报告：[{target.name}]({target.as_posix()})\n\n最终UI目录：`{ui_folder.as_posix()}`。\n''',encoding='utf-8')
    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if key not in ('src', 'href') or not value:continue
                parts=urlsplit(value)
                assert not parts.scheme and not parts.netloc, value
                assert (OUT/unquote(parts.path)).resolve().is_file(), value
    Links().feed(body)
    print(str(target),flush=True)


if __name__=='__main__':main()
