"""Openable evidence for native Agent page reads, not a cloud quality benchmark."""
from html import escape
import json
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/library-tool-receipt-acceptance-20261021'
TITLE='导师原页回查与阅读版本验收'
UI=ROOT/'build/library-tool-receipt-ui-20261021-3'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    case=load(UI/'case.json');ui=load(UI/'ui-report.json')
    baseline=ET.parse(ROOT/'build/library-tool-receipt-20261021/baseline.xml').getroot().findall('.//testcase')
    tests=ET.parse(ROOT/'build/library-tool-receipt-20261021/final-regression.xml').getroot().findall('.//testcase')
    failures=sum(t.find('failure') is not None for t in baseline)
    assert ui['passed'] and ui['external_model_requests']==0 and tests
    assert all(t.find(k) is None for t in tests for k in ('failure','error','skipped'))
    notes={
        'partial':('只回查第二页的100个字符','实际返回原页第6–105字符，记录旧阅读模型及当时末页50%的边界。标题、偏移和未返回部分不冒充已核对正文。'),
        'visual':('只返回保存的AI图像记录','原页OCR本次没有返回文字；AI记录的字符范围单独显示，不能称作教材原文引语。'),
        'empty':('偏移已越过末尾','工具返回空文本，历史明确记为“本次未提供”。不会凭指定了页码就标为已回查原文。'),
        'all':('完整返回这个已读节点的缓存文本','实际提供两页的原页文字与AI图像记录，不代表逐像素重看原图、理解无误或整本书已阅读。')}
    cases=[dict(row,title=notes[row['label']][0],note=notes[row['label']][1]) for row in case['tool_cases']]
    checks=''.join('<li>'+escape(value)+'</li>' for value in ui['checks'])
    payload=json.dumps(cases,ensure_ascii=False).replace('<','\\u003c')
    html=TEMPLATE
    for key,value in {'COUNT':str(len(tests)),'BASE_FAIL':str(failures),'BASE_PASS':str(len(baseline)-failures),
                      'UI_COUNT':str(len(ui['checks'])),'CHECKS':checks,'PAYLOAD':payload,
                      'OLD_ID':case['old_reading_id'][:8],'NEW_ID':case['new_reading_id'][:8]}.items():
        html=html.replace('__'+key+'__',value)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/(TITLE+'.html')).write_text(html,encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({'python_checks':len(tests),'new_focused_checks':18,
        'baseline_failures':failures,'baseline_passes':len(baseline)-failures,'node_syntax_checks':4,
        'actual_ui_checks':len(ui['checks']),'native_tool_dispatches':4,'cloud_model_requests':0,
        'physical_android_test':False,'packaged':False,'mobile_shell':63},ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUT/(TITLE+'.html'))


TEMPLATE=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>导师原页回查与阅读版本验收</title>
<style>:root{font:16px/1.9 system-ui,"Microsoft YaHei",sans-serif;color:#264136;background:#edf1e8}*{box-sizing:border-box}body{max-width:1190px;margin:auto;padding:26px 20px}header,section{padding:26px;margin:20px 0;background:#fffefa;border:1px solid #ccd8cb;border-radius:19px;min-width:0}h1{font-size:32px;line-height:1.4}h2{font-size:23px}h3{font-size:18px}a{color:#1b6b51;overflow-wrap:anywhere}.badge{display:inline-block;padding:5px 12px;background:#e4ecdf;border-radius:20px;font-size:13px}.notice{padding:15px 18px;border-left:4px solid #aa854b;background:#fff1d8;border-radius:6px}.subtle{color:#576c5c;font-size:13px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.metrics>div,.card{border:1px solid #cbd8c8;border-radius:12px;padding:17px;background:#f6f8f0;min-width:0}.metrics strong{display:block;font-size:25px}.columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;margin-top:16px}.card h3{margin-top:0}select{font:inherit;color:inherit;background:#eef4e8;border:1px solid #9eb8a4;padding:10px 12px;max-width:100%;border-radius:10px;cursor:pointer}select:focus-visible,summary:focus-visible{outline:3px solid #4b997d;outline-offset:3px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:450px;overflow:auto;font:13px/1.85 Consolas,"Microsoft YaHei",monospace;border:1px solid #d5dfcd;background:#eff3e8;border-radius:10px;padding:13px;margin-bottom:0}summary{cursor:pointer;font-weight:600}details{margin:15px 0}li{margin:8px 0}.shots{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:17px;align-items:start}.shots img{display:block;max-width:100%;height:auto;border:1px solid #cbd8c8;border-radius:12px}.shots a{min-width:0}.label{margin:10px 0;padding:9px 12px;background:#e1ecdf;border-radius:9px;overflow-wrap:anywhere}code{overflow-wrap:anywhere}@media(max-width:760px){body{padding:10px}header,section{padding:16px}h1{font-size:25px}.columns,.metrics,.shots{grid-template-columns:minmax(0,1fr)}}</style></head><body>
<header><span class="badge">STUDYFORGE · 2026-10-21 · 源码验收</span><h1>导师回查了哪一版、哪一页、哪一段？</h1><p>本轮继续完善知识库的学习依据。导师逐页回查后，记录现在绑定<strong>当时实际返回的文字</strong>，保留阅读版本、页内范围和字符位置。新版笔记、重命名或修改目录不会反过来改写这份历史。</p><p><a href="../../验收最新版.vbs">打开最新版源码</a> · <a href="../../web/help/guide.html#library">软件内使用指南</a> · <a href="../../docs/导师原页回查与阅读版本验收.md">完整实施记录</a></p><div class="notice">这是来源记录修复，不是新模型教学能力评测。本轮没有云端生成请求、没有重新OCR未读章节、没有修改学生画像，也没有把已安装EXE替换为新版。</div></header>
<section><h2>可复现的问题与修复结果</h2><div class="metrics"><div><strong>__BASE_FAIL__项失败 → 修复</strong>修复前8项中__BASE_PASS__项通过</div><div><strong>__COUNT__项通过</strong>最终关联Python回归</div><div><strong>__UI_COUNT__项操作通过</strong>电脑＋配对HTTPS手机页面</div></div><p>原工具已经能够按冻结的旧阅读版本读取正文，但记录中缺少该版本和实际字符范围。导航随后用当前目录补填标题／范围；只读到标题或返回空字符串时，还可能显示为“已回查原文”。这些不是模型生成的猜测，而是本机可复现的来源记录错误。</p><p>现在由同一次实际读取计算片段范围，并随记录保存。仍按原来的窗口分页读取，不拼接整章、不重复保存原文或长笔记。保留后续位置，导师可按需继续；记录不认证内容正确。</p><p><a href="../library-tool-receipt-20261021/baseline.xml">修复前问题复现</a> · <a href="../library-tool-receipt-20261021/final-regression.xml">最终回归</a> · <a href="../library-tool-receipt-ui-20261021-3/ui-report.json">两端界面操作记录</a></p></section>
<section><h2>四次原生工具读取：查看真实返回与保存信息</h2><p class="subtle">在独立测试数据中导入3页实际PDF、提取已授权页、运行原生Agent工具派发。页面只展示工具原样返回与记录，不用AI重写成品。没有经过真实云模型自行决定调用的那一步。</p><label for="example">读取场景</label> <select id="example"></select><h3 id="caseTitle"></h3><p id="caseNote"></p><div class="columns"><article class="card"><h3>实际返回的工具正文</h3><div id="textMetric" class="label"></div><pre id="returned" class="raw-output"></pre></article><article class="card"><h3>保存的版本、范围与指纹</h3><div id="versionMetric" class="label"></div><pre id="receipt" class="raw-output"></pre></article></div><p class="subtle">全局偏移包含来源标题；原页／AI图像记录的字符位置分别计算。SHA-256只用于确认同一输入，不证明原文无误。原生工具窗口仍可能截在句子或公式中间，必要时须继续读取上下文。</p><p><a href="../library-tool-receipt-ui-20261021-3/case.json">四次原生工具的完整输出</a></p></section>
<section><h2>阅读版本与旧记录边界</h2><p>任务固定的是 <code>saved-tool-reader</code> · 版本 <code>__OLD_ID__</code>。之后新增有效的 <code>later-tool-reader</code> · 版本 <code>__NEW_ID__</code>，仍不能冒充前一任务实际读取的版本。读取后再改名、把末页范围从50%调到60%，历史依然显示原来的标题和50%边界，并提示“历史范围已变化”。</p><ul><li>仅返回AI图像记录时，原页OCR显示“本次未提供文字”，两类来源分开。</li><li>空返回、仅标题返回不记作读过正文；已提供范围以实际返回层为准。</li><li>旧记录没有实际阅读版本和字符范围，明确标为无法追溯，不用今天的书库补认昨天的读取。</li><li>记录留在原对话；其他项目看不到，也不进入学习画像、作答分数或私有批改结果。</li></ul></section>
<section><h2>两端实际界面与手机阅读宽度</h2><p>电脑完成展开、真实滚轮滚动、项目切换、返回和整页刷新；手机通过实际HTTPS配对和设备审批，验证相同历史与刷新恢复。手机学习选项原先有多层嵌套滚动条，本轮减少嵌套，让外层选项页滚动，长来源详情仍可单独滚动。</p><details><summary>展开__UI_COUNT__项界面检查</summary><ul>__CHECKS__</ul></details><div class="shots"><a href="../library-tool-receipt-ui-20261021-3/desktop-tool-source.png"><img src="../library-tool-receipt-ui-20261021-3/desktop-tool-source.png" alt="电脑端保存的原页回查详情"></a><a href="../library-tool-receipt-ui-20261021-3/phone-tool-source-320.png"><img src="../library-tool-receipt-ui-20261021-3/phone-tool-source-320.png" alt="320像素配对手机页面的回查详情"></a></div><p class="subtle">320／390像素页面无横向溢出，控制台错误0项。手机验收使用真实浏览器引擎和配对HTTPS窗口，不是实体安卓触控或跨网稳定性测试。</p></section>
<section><h2>怎样打开验收</h2><ol><li>在系统托盘彻底退出旧StudyForge，再双击上方“打开最新版源码”，避免仍打开旧后台服务。</li><li>进入已有阅读记录的书库，在工作台引用相关节点，请导师回查指定已读页；随后在“书库检索记录”展开“原页回查记录”。</li><li>核对阅读模型、短版本号、PDF页码、原页／AI层字符范围与后续读取位置。切换对话后返回，记录应继续存在。</li><li>手机连接同一源码实例后刷新，在右上角“⋯ → 学习选项 → 书库检索记录”查看；公共手机壳为v63。</li></ol><p>本轮没有重新打包。旧EXE不会因源码修改自动变成新版。</p></section>
<section><h2>仍需实测的部分</h2><p>没有新增固定审查轮次或云端请求；新增少量来源元数据会使工具响应略长。没有测量完整任务提速比例，也不声称全软件内存、长视频、整库教学质量已解决。下一步更有价值的是用真实学习问题核对“找得准 → 读对范围 → 讲清条件”整条链路，同时保留错误与未读范围。</p></section>
<script type="application/json" id="examples">__PAYLOAD__</script><script>
const examples=JSON.parse(document.getElementById('examples').textContent),select=document.getElementById('example');
examples.forEach((value,index)=>{const option=document.createElement('option');option.value=index;option.textContent=value.title;select.append(option);});
function show(){const value=examples[Number(select.value)||0],receipt=value.receipt,source=receipt.sources[0];document.getElementById('caseTitle').textContent=value.title;document.getElementById('caseNote').textContent=value.note;document.getElementById('returned').textContent=value.returned_text||'（空字符串：没有返回正文）';document.getElementById('receipt').textContent=JSON.stringify(receipt,null,2);document.getElementById('textMetric').textContent=receipt.context_characters+' 字符 · '+(source.included?'实际提供了以下层／片段':'未提供正文');document.getElementById('versionMetric').textContent=source.library_reading.model+' · 版本 '+source.library_reading.id.slice(0,8);}
select.onchange=show;show();
</script></body></html>'''


if __name__=='__main__':main()
