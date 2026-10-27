"""Keep real replies, including the failed printed-tool reply, inspectable."""
import base64
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

from scripts.build_teaching_comparison import inline_script

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/lesson-read-scope-acceptance-20261021'
REAL = ROOT / 'build/lesson-source-real-20261021-1'
UI = ROOT / 'build/lesson-read-scope-ui-20261021-1'
TITLE = '原文读取范围与讲解核对验收'


def load(path): return json.loads(path.read_text(encoding='utf-8'))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tests = ET.parse(ROOT / 'build/lesson-read-scope-final-regression-20261021.xml').getroot().findall('.//testcase')
    assert tests and all(t.find(k) is None for t in tests for k in ('failure','error','skipped'))
    ui = load(UI / 'content-rounds-ui-report.json')
    assert ui['passed'] and ui['final_state']['requests'] == 4
    before = load(ROOT / 'build/lesson-source-request-20261021/baseline/results.json')
    after = load(ROOT / 'build/lesson-source-request-20261021/fixed/results.json')
    table = []
    labels = {'chapter':'选中旧AI“第2章”','page':'选中旧AI“第2页”','stored_page':'仅上传未解析的PDF + 旧AI“第2页”',
        'explicit_pages':'旧AI“第1章” + 学生明确只核对原PDF第2页','explicit_excerpt':'学生明确只读一段，稍后提供原文'}
    def scope(row):
        pages = [str(i) for i,key in enumerate(('first_page_in_system','second_page_in_system'),1) if row[key]]
        return '原PDF第'+'、'.join(pages)+'页' if pages else ('等待明确范围／选段' if row['waiting_for_scope'] else '未读取')
    for old,new in zip(before['cases'],after['cases'],strict=True):
        assert old['case'] == new['case'] and old['public_question'] == new['public_question']
        table.append('<tr><th>'+escape(labels[old['case']])+'</th><td>'+scope(old)+'</td><td>'+scope(new)+'</td></tr>')
    samples = load(REAL / 'results.json')
    replay = load(REAL / 'protocol-replay-after-fix.json')['rows']
    assert len(samples) == 4 and sum(row['model_requests'] for row in samples) == 4
    cases = load(REAL / 'inputs.json')['cases']
    comments = {
        ('injective','legacy'):'旧输入只有PDF第2页，缺少第1页定义域。回答指出缺条件，这部分质疑有依据，不能算成模型凭空犯错；但它没能据完整原文说明非负定义域和零边界。',
        ('injective','fixed'):'实际收到第1页的[0,+∞)条件，正确指出“x+y始终大于0”错误；分情况处理x+y=0，解释非负定义域如何排除相反数。这次28.87秒，比旧样例20.68秒慢，不声称提速。',
        ('causal','fixed'):'结合原文的自选记笔记、无随机分组、未测先前成绩与动机，区分相关、因果、显著与混杂；也区分横截面的成绩更高与前后提高。仍出现引文定位提示，统计显著的口语解释需要结合后文的模型前提阅读，不认证整篇无误。',
        ('causal','legacy'):'实质失败：正文停在“我先读取”，随后打印DSML伪工具调用。未调用读取工具、未核对两句话。旧程序却保存为completed。原输出保留；新版回放会识别为未完成，不能把6.14秒算成更快完成讲解。',
    }
    rendered = []
    for row in samples:
        text = (REAL / row['answer_file']).read_text(encoding='utf-8')
        actual = load(REAL / (row['case']+'-'+row['phase']+'-requests.json'))
        trace = row['http_attempts'][0]
        assert len(actual) == 1 and sha256(json.dumps(actual[0],ensure_ascii=False,sort_keys=True).encode()).hexdigest() == trace['body_sha256']
        failed = next(r for r in replay if (r['case'],r['phase']) == (row['case'],row['phase']))['current_protocol_status'] != 'text_accepted'
        rendered.append({**row, 'text':text,'failed':failed,'comment':comments[(row['case'],row['phase'])],
            'text_sha256':sha256(text.encode()).hexdigest(), 'request_file':row['case']+'-'+row['phase']+'-requests.json'})
    assets = ROOT / 'web/vendor'
    css = (assets/'katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((assets/'fonts'/m[1]).read_bytes()).decode()+')',css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    libraries = '\n'.join(inline_script((assets/name).read_text(encoding='utf-8')) for name in ('marked.js','purify.js','katex.js'))
    renderer = inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8'))
    payload = json.dumps({'cases':cases,'samples':rendered},ensure_ascii=False).replace('<','\\u003c')
    page = TEMPLATE.replace('__CSS__',css).replace('__LIBRARIES__',libraries).replace('__RENDERER__',renderer).replace('__PAYLOAD__',payload)
    page = page.replace('__TABLE__',''.join(table)).replace('__COUNT__',str(len(tests)))
    (OUT/(TITLE+'.html')).write_text(page,encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({'program_checks':len(tests),'node_checks':3,'ui_checks':len(ui['checks']),
        'actual_requests':4,'substantive_answers':3,'failed_printed_tool_answers':1,
        'controlled_source_requests':10,'controlled_ui_requests':4,'changed_default_model':False,
        'packaged':False,'report_build_model_requests':0},ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUT/(TITLE+'.html'))


TEMPLATE = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>原文读取范围与讲解核对验收</title>
<style>__CSS__
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#203f36;background:#edf3ed}*{box-sizing:border-box}body{max-width:1280px;margin:auto;padding:26px 18px;line-height:1.85}header,section,.answer{background:#fffefa;border:1px solid #ccdbce;border-radius:18px;padding:24px;margin:18px 0;min-width:0}h1{font-size:31px;line-height:1.4}h2{font-size:23px}h3{font-size:19px}a{color:#14634b;overflow-wrap:anywhere}.notice,.review{padding:13px 16px;border-left:4px solid #bd8a3c;background:#fff3d9}.badge{padding:5px 9px;border-radius:20px;background:#e0eee2;font-size:13px}.bad{background:#f6dfd7;color:#79291f}.muted{font-size:13px;color:#56685f}.compare{display:grid;grid-template-columns:1fr 1fr;gap:18px}.answer{margin:0;padding:18px;overflow:hidden}.table-scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:580px}td,th{text-align:left;vertical-align:top;border:1px solid #cfdbd0;padding:9px 12px}summary{cursor:pointer;font-weight:650}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.8 Consolas,monospace;background:#eff3eb;padding:12px;border-radius:9px}blockquote{margin:12px 0;padding:10px 14px;border-left:3px solid #6e9780;background:#eef5ee;overflow-wrap:anywhere}.lesson-explanation{font-size:16px;overflow-wrap:anywhere}.lesson-explanation h1{font-size:23px}.lesson-explanation h2{font-size:21px}.lesson-explanation h3{font-size:18px}.lesson-explanation table{display:block;overflow:auto;min-width:0}.display-math{display:block;max-width:100%;overflow-x:auto}.katex{font-size:1.07em}img{max-width:100%;height:auto;border:1px solid #ccd7cf;border-radius:12px}.shots{display:grid;grid-template-columns:2fr 1fr;gap:16px;align-items:start}.shots a{min-width:0}details{margin:12px 0}li{margin:7px 0}button{font:inherit;color:#244a3b;border:1px solid #9bb9a4;background:#ecf4e9;border-radius:9px;padding:9px 14px;cursor:pointer}button:focus-visible,summary:focus-visible{outline:3px solid #549a81;outline-offset:3px}@media(max-width:850px){.compare,.shots{grid-template-columns:1fr}body{padding:12px}header,section{padding:16px}h1{font-size:25px}}
</style></head><body>
<header><div>STUDYFORGE · 2026-10-21</div><h1>先把原文读对，才能核对讲解</h1><p>本轮修复了旧AI讲解的章节／页码误改原PDF读取范围的问题，并隔离不同读取范围的内部工具历史。没有增加固定审核轮次，也没有更换默认模型。</p><p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../web/help/guide.html#teaching-review">软件内操作指南</a> · <a href="../../docs/原文读取范围与讲解核对验收.md">详细验收与边界</a></p><div class="notice"><strong>保留失败的实际输出。</strong>本页含4次真实DeepSeek请求：3份实质回答、1份伪工具文本失败。另有受控原生请求复现和两端界面检查，分开计数。小样本不证明所有学科、长视频速度或内存问题已经解决；本轮源码未打包。</div></header>
<section><h2>修复了什么</h2><ol><li>选择历史讲解的“第2章”／“第2页”，只定位旧AI内容，不能变成原PDF的读取指令。</li><li>真正限定原文件的要求来自你填写的补充，例如“只核对原PDF第2页”。仅上传未解析的文件仍等待明确读取范围；旧AI原句不是原文件选段。</li><li>独立任务继承原读取范围；页码、选段或全文授权改变时，重新建立内部工具上下文，同一对话公开聊天记录保留。相同页码的普通改问法仍可复用。</li><li>识别本轮实际出现的裸DSML伪工具文本。它不会执行；响应只重试未完成的这一步，仍失败则报错，不保存成已完成核对。协议代码示例和引用日志仍可正常讲解。</li></ol><p class="muted">自然语言范围解析仍采用现有有限规则，不保证能理解任意否定、复杂页码或含糊转述；本轮没有自动替你扩大未读资料范围。</p></section>
<section><h2>原生请求复现：旧输入与修复后输入</h2><p>相同资料、相同学生提问；只切换范围识别。5对复现共10次受控模型请求，非外部模型能力测评。原本不该读取的未解析PDF也纳入了检查。</p><div class="table-scroll"><table><thead><tr><th>操作</th><th>修复前</th><th>修复后</th></tr></thead><tbody>__TABLE__</tbody></table></div><p><a href="../lesson-source-request-20261021/baseline/results.json">修复前完整记录</a> · <a href="../lesson-source-request-20261021/fixed/results.json">修复后完整记录</a> · <a href="../lesson-source-request-20261021/fixed/source.pdf">两页原PDF夹具</a></p></section>
<section><h2>四份真实回答：阅读全文再判断</h2><p>DeepSeek配置调用名<code>deepseek-flash</code>、推理high、直观与专业并重、精学。每组同一份短合成原资料、旧错误讲解和提问，两方案各一次、独立新对话；本次关闭工具与联网，没有视频、OCR或Word导出。对话ID、路径、缓存和服务波动不同，非严格盲测。不是DeepSeek网页端测试，也不由调用名确认后端具体版本。</p><p>旧方案的缺条件质疑有时正是漏读输入导致；不能把它全算成模型知识错误。修复后两个样例能依据完整条件纠正旧讲解，但仍有引用和措辞限制。下方包括旧程序误标完成的失败原样，不能按耗时把它评为最快成功。</p><div id="cases"></div></section>
<section><h2>实际功能检查</h2><p><strong>__COUNT__项Python相关回归通过，3项共享核查组件Node检查通过。</strong>此前范围复现测试为4失败／1通过，修复后对应场景通过；新增Codex同对话范围切换、DeepSeek内部历史复用，以及伪工具文本恢复／持续失败检查。</p><p>6项实际Electron／配对HTTPS界面操作检查通过。原生快速DOCX任务2次受控请求，电脑和手机核对各1次，共4次受控请求；两次核对实际输入都含PDF两页标记，旧AI标题为“第2章”。原已跳过问卷保留，学习事件、画像条目、评分、题单均为0。手机320／390像素无页面横向溢出，控制台错误0项。</p><p>这是配对HTTPS手机宽度窗口，不是实体安卓人工验收。未在Microsoft Word人工检查分页，也未重测长视频、总内存或全学科正确性。</p><p><a href="../lesson-read-scope-final-regression-20261021.xml">最终Python回归</a> · <a href="../source-request-scope-baseline-20261021.xml">修复前失败证据</a> · <a href="../lesson-read-scope-ui-20261021-1/content-rounds-ui-report.json">两端操作记录</a> · <a href="../lesson-source-real-20261021-1/protocol-replay-after-fix.json">真实失败文本本机回放</a></p><div class="shots"><a href="../lesson-read-scope-ui-20261021-1/电脑继续核对讲解.png"><img src="../lesson-read-scope-ui-20261021-1/电脑继续核对讲解.png" alt="电脑端第2章讲解内容核对记录"></a><a href="../lesson-read-scope-ui-20261021-1/手机继续核对-390.png"><img src="../lesson-read-scope-ui-20261021-1/手机继续核对-390.png" alt="配对手机核对记录"></a></div></section>
<section><h2>你可以这样验收</h2><ol><li>从系统托盘退出旧StudyForge，打开上方“启动最新版源码”。现有已安装EXE没有被本轮源码自动替换。</li><li>进入成果的理解反馈，点“核对讲解新疑问”。选择旧AI章节，填写疑问，再提交回应。</li><li>若需限制原PDF页码，在补充里明确写出；未解析整本时先使用资料的范围入口。选旧AI章节不会替你读取未授权的原PDF。</li><li>失败时问题和原句保留，可以重试。本轮不自动把这类质疑记进学习画像，不扣分，不出题。</li></ol></section>
<script type="application/json" id="data">__PAYLOAD__</script><script>__LIBRARIES__
__RENDERER__
const data=JSON.parse(document.getElementById('data').textContent),root=document.getElementById('cases');
const node=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;};
for(const example of data.cases){
 const group=node('div','case-group');group.dataset.case=example.id;group.append(node('h3','',example.title));
 const prompt=node('details');prompt.append(node('summary','','原资料、旧AI讲解和实际问题'),node('pre','',example.pages.map((p,i)=>'PDF第'+(i+1)+'页：'+p).join('\n\n')+'\n\n旧AI讲解：\n'+example.lecture+'\n\n提问：'+example.question));group.append(prompt);
 const pdf=node('a','', '原PDF夹具');pdf.href='../lesson-source-real-20261021-1/'+example.id+'.pdf';group.append(pdf);
 const grid=node('div','compare');
 for(const row of data.samples.filter(r=>r.case===example.id)){
  const card=node('article','answer');card.append(node('span','badge'+(row.failed?' bad':''),(row.phase==='fixed'?'修复后读取':'旧读取方式')+' · '+(row.failed?'实质失败，旧程序误标完成':'实质正文')));
  card.append(node('p','muted',row.seconds+'秒 · '+row.model_requests+'次实际请求 · 调用名 '+row.http_attempts[0].returned_model),node('p','review',row.comment));
  const body=node(row.failed?'pre':'div','model-answer');if(row.failed)body.textContent=row.text;else renderLessonText(body,row.text);card.append(body);
  const raw=node('details','raw-answer');raw.append(node('summary','','查看逐字原始回复与指纹'),node('pre','',row.text),node('pre','',row.text_sha256));card.append(raw);
  const link=node('a','','实际请求正文JSON（不含密钥／隐藏思考）');link.href='../lesson-source-real-20261021-1/'+row.request_file;card.append(link);
  const metrics=node('details');metrics.append(node('summary','','实际返回用量与耗时'),node('pre','',JSON.stringify(row.http_attempts,null,2)));card.append(metrics);grid.append(card);
 }group.append(grid);root.append(group);
}
</script></body></html>'''


if __name__ == '__main__': main()
