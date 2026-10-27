"""Offline public answers, failed JSON, native replay and a small exact demo."""
import hashlib
from html import escape
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/teaching-witness-acceptance-20261022'
TITLE='教学例子前提与代数核对验收'
REVIEWS={
 'math':'两版都正确纠正“只能取一半”，说明更小正半径和两个最终门槛。候选没有形成明确的教学优势；两版都展开了多种半径，未完全符合“只补一个卡点”的简短期待。',
 'gauss':'两版都算对六面净通量。原规则说远处电荷，候选说很远的大带电板，都未明确有限现实装置仅近似均匀；新增前提措辞仍未解决目标问题。补入散度对这个追问也非必需。',
 'causal':'两版都给出83与77、差6分的混杂例子，并明确因果作用为零的设定。原规则用层内标准差10并纳入组间差异，方差116正确；候选另设两组整体标准差约10，属于不同设定，不能直接判错。但两版对统计显著性的口语解释仍缺检验假设，候选没有稳定胜出。'}


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    from studyforge.algebra_hints import candidates
    from studyforge.teaching_policy import REASONING_TEACHING_RULES
    from scripts.probe_example_premises import OLD,NEW
    assert OLD in REASONING_TEACHING_RULES and NEW not in REASONING_TEACHING_RULES
    gate=load(ROOT/'build/algebra-witness-20261021/final-command-20261022.json')
    assert gate['exit_code']==0 and gate['frozen_production_unchanged'] and not any(gate['tests'][k] for k in ('failure','error','skipped'))
    replay=load(ROOT/'build/teaching-witness-replay-20261022-2/report.json');assert replay['passed']
    pairs=[];live=ROOT/'build/example-premises-live-20261021-1';inputs=load(live/'cases.json')
    for case in inputs:
        rows=[]
        for arm in ('baseline','candidate'):
            result=next(row for row in load(live/'report.json') if row['case']==case['name'] and row['arm']==arm)
            assert result['status']=='completed' and len(result['calls'])==1
            usage=result['calls'][0]['usage']
            rows.append({'arm':arm,'answer':(live/result['answer_file']).read_text(encoding='utf-8'),
                'seconds':result['seconds'],'prompt_tokens':usage['prompt_tokens'],'total_tokens':usage['total_tokens'],
                'file':'../'+live.name+'/'+result['answer_file'],'request':'../'+live.name+'/'+result['calls'][0]['file']})
        pairs.append({'name':case['name'],'title':{'math':'数学：极限唯一性','gauss':'物理：净通量与电场','causal':'社会科学：大样本与因果'}[case['name']],
            'question':case['question'],'quote':case['quote'],'review':REVIEWS[case['name']],'rows':rows})
    audits=[]
    for number in (1,2):
        folder=ROOT/'build'/f'algebra-witness-review-live-20261021-{number}'
        for result in load(folder/'report.json'):
            raw_file=result['case']+'-'+result['arm']+'.json'
            decoded=next(row for row in replay['decoded'] if row['experiment']==number and row['case']==result['case'] and row['arm']==result['arm'])
            raw=(folder/raw_file).read_text(encoding='utf-8')
            assert hashlib.sha256(raw.encode()).hexdigest()==decoded['raw_sha256']
            audits.append({'title':f'第{number}轮 · '+('无附加条件' if result['case']=='unconditional' else '给定a=2')+' · '+('修复前输入' if result['arm']=='baseline' else '带本机线索'),
                'raw':raw,'raw_file':'../'+folder.name+'/'+raw_file,'passed':decoded['passed'],'strict_json':decoded['strict_json'],
                'seconds':result['seconds'],'issue_count':len(decoded['issues']),'error':result.get('error',''),
                'note':'首轮未正确挂接非流式计量，不用于token或请求体对比；条件原稿“只在”措辞也有额外限定歧义。' if number==1 else '修正了实验计量并明确各步条件；同组两份资料与草稿相同。'})
    namespace={'__name__':'studyforge.old_algebra_hints','__package__':'studyforge'}
    path=ROOT/'build/algebra-witness-20261021/baseline-algebra-hints.py';exec(compile(path.read_text(encoding='utf-8'),str(path),'exec'),namespace)
    formula='$$a+b=b+a=2a+b-2$$';assert namespace['candidates'](formula)==[]
    recovered=candidates(formula);assert recovered[0]['substitution']=={'a':'3','b':'5'}
    native=[]
    for row in replay['jobs']:
        native.append({'title':('无附加条件' if row['case']=='unconditional' else '给定a=2')+' · '+('旧核查返回回放' if row['arm']=='baseline' else '新核查返回回放'),
            'content':row['content'],'file':'../teaching-witness-replay-20261022-2/'+row['docx'],
            'note':f"{row['controlled_model_requests']}次受控请求，0次外部调用；核查passed={row['review_passed']}，实际局部修订问题数{len(row['locally_corrected_issues'])}；"+
                ('保留本机待核对提示。' if row['conditional_warning_retained'] else '没有残留本机提示。')})
    payload=json.dumps({'pairs':pairs,'audits':audits,'native':native},ensure_ascii=False).replace('<',r'\u003c')
    style=STYLE
    html=TEMPLATE.replace('__STYLE__',style).replace('__COUNT__',str(gate['tests']['total'])).replace('__PAYLOAD__',payload)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/(TITLE+'.html')).write_text(html,encoding='utf-8')
    manifest={'date':'2026-10-22','regression':gate['tests'],'source_hashes':gate['production_after'],
        'candidate_integrated':False,'actual_teaching_samples':6,'actual_review_samples':8,
        'invalid_original_json':sum(not row['strict_json'] for row in replay['decoded']),
        'replayed_original_review_outputs':len(replay['decoded']),'native_docx_jobs':4,'controlled_replay_requests':8,
        'new_fixed_model_rounds':0,'physical_android_test':False,'business_ui_retested':False,'docx_layout_rendered':False,'packaged':False,
        'mobile_shell_unchanged':65,'reviews':REVIEWS,'witness':recovered}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUT/(TITLE+'.html'))


STYLE=r'''
*{box-sizing:border-box}html{color-scheme:light}body{margin:0;color:#233b35;background:radial-gradient(ellipse at top left,#e7efe2,transparent 65%),#f4f3ed;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}
header,section{max-width:1160px;margin:24px auto;padding:28px 32px;background:#fffefa;border:1px solid #dce5da;border-radius:24px;box-shadow:0 8px 30px #234d3910}
header{margin-top:40px;border-top:5px solid #267358}h1{font-size:32px;line-height:1.45;max-width:900px}h2{font-size:24px;line-height:1.5;margin-top:0}h3{font-size:19px}
a{color:#17654f;text-decoration-thickness:1px;text-underline-offset:4px}a:hover{color:#0b3e2f}a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #8a671b;outline-offset:3px}
p{margin:14px 0}.badge{display:inline-block;border-radius:10px;background:#eaf3e9;color:#315e42;padding:5px 10px;font-size:13px;font-weight:600}
.notice{border-left:4px solid #bc9b49;background:#faf4e3;padding:14px 18px;border-radius:0 12px 12px 0;line-height:1.8}.columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.card{min-width:0;border:1px solid #d8e3d8;background:#fff;padding:20px;border-radius:18px}.card h3{margin-top:0}.card>p.badge{margin-top:0}
select{width:min(100%,420px);padding:10px;border:1px solid #b5cbbc;border-radius:10px;color:#233b35;background:#fff;font:inherit;margin:8px 0}
button{border:1px solid #b8cdbd;border-radius:10px;background:#edf4ed;color:#225a42;font:inherit;padding:8px 12px;margin:6px 4px 6px 0;white-space:normal}
blockquote{margin:16px 0;background:#f0f3ee;border-left:4px solid #95af9a;padding:14px 18px;border-radius:0 10px 10px 0}
table{border-collapse:collapse;font-size:14px;max-width:100%;margin:16px 0}th,td{padding:7px;border:1px solid #d9e3db;text-align:left}th{background:#edf3ec}
code{padding:2px 5px;border-radius:5px;background:#eef1ea;font:14px/1.7 Consolas,monospace}.raw{background:#f1f3ee;border-radius:12px;padding:16px;font:13px/1.7 Consolas,monospace}
summary{cursor:pointer;color:#245b43;font-weight:600}summary:hover{color:#102e20}details[open] summary{margin-bottom:14px}
.answer,.native{padding-right:10px;scrollbar-gutter:stable;overflow-wrap:anywhere}.answer p:first-child{margin-top:0}.answer:focus-visible{outline:3px solid #267358}
@media(max-width:720px){body{font-size:15px}header,section{margin:12px 8px;padding:20px 16px;border-radius:18px}header{margin-top:14px}h1{font-size:25px}h2{font-size:21px}.columns{grid-template-columns:1fr}.card{padding:16px}.notice{padding:12px}.raw{padding:10px}}
'''

TEMPLATE=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>教学例子前提与代数核对验收</title><link rel="stylesheet" href="../../web/vendor/katex.css"><style>__STYLE__ .answer,.raw,.lesson{max-height:640px;overflow:auto}.small{font-size:14px}.demo{display:grid;grid-template-columns:1fr 1fr;gap:16px}.demo output{font-size:28px;font-weight:700}input[type=range]{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}button{cursor:pointer}label{display:block}details{margin:12px 0}.audit-card{padding:18px;border:1px solid #ccd9cf;border-radius:18px;background:#fffdf7;margin:16px 0}.katex-display{overflow-x:auto;overflow-y:hidden}.native{max-height:750px;overflow:auto}@media(max-width:640px){.demo{grid-template-columns:1fr}}</style></head><body>
<header><span class="badge">STUDYFORGE · 2026-10-22 · 教学核验</span><h1>保留好解释，修复能确认的漏检与格式失败</h1><p>本轮继续用同一模型检验例子的前提与方法解释：六份真实讲解没有证明新增措辞更好，候选未采用。两项实装改进是固定数值碰巧相等时的漏检，以及JSON公式定界符导致的额外格式修复。</p><p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../docs/教学例子前提与代数核对验收.md">完整实施记录</a> · <a href="manifest.json">证据清单与源码指纹</a></p><div class="notice">源码已更新，本轮未打包。手机共用同一电脑后端；未修改界面脚本或公共壳v65。这不是所有学科、长视频、全部教学质量、全应用内存或实体安卓的全面验收。</div></header>
<section><h2>为何一个数值算对，仍不能证明一般改写正确？</h2><p>例子：$a+b=b+a=2a+b-2$。最后一步只在$a=2$成立，若没有这个附加条件就不能作为一般恒等式。旧本机检查固定代入$a=2,b=5$，两边碰巧都是7，从而漏掉了线索。</p><div class="demo"><div class="card"><h3>试着移动a，观察两边</h3><label>a = <span id="aValue">2</span><input id="a" type="range" min="-5" max="10" value="2" step="1"></label><label>b = <span id="bValue">5</span><input id="b" type="range" min="-5" max="10" value="5" step="1"></label><button id="initial">旧代入：a=2，b=5</button> <button id="witness">新区分代入：a=3，b=5</button></div><div class="card"><p>a+b = <output id="left">7</output></p><p>2a+b−2 = <output id="right">7</output></p><p id="verdict" class="notice"></p></div></div><p>新版使用精确有理数和两边线性系数的差异，必要时改变一个确实影响差异的变量，得到能区分两边的数值；不靠再随机抽几个点。原先已经能区分的提示保持原值与顺序。</p><div class="notice">这个代入未必符合正文的附加条件。若题目已明确给定a=2，等式可以成立；本机输出仍只是“请核对条件”的线索，不自动改判学生答案。非线性、变量分母、引文、代码、普通单条方程等原有限制保留。</div><p><a href="../algebra-witness-20261021/baseline-algebra-hints.py">修复前实现</a> · <a href="../algebra-witness-20261021/baseline-corrected.xml">旧版有效复现：15项失败、8项通过</a></p></section>
<section><h2>六份真实教学回答：增加前提措辞未稳定变好</h2><label for="pair">选择对照问题</label><select id="pair"></select><p id="question"></p><blockquote id="quote"></blockquote><p id="manual" class="notice"></p><div id="pairRows" class="columns"></div><p>原生准备的同一问题、资料、旧AI原句和设置，只替换一小段共同教学措辞。模型请求名deepseek-flash，high，精学、直观与专业并重；不执行工具、不联网。三组各采一次，候选本次分别17.96／17.528／28.708秒，原规则25.487／22.888／30.707秒。回答更快不能抵消条件问题；缓存与随机波动也未被排除，不据此推出稳定提速。默认教师规则没有更换。</p><p><a href="../example-premises-live-20261021-1/policy.json">完整旧／候选措辞</a> · <a href="../example-premises-live-20261021-1/cases.json">三组完整消息</a> · <a href="../example-premises-live-20261021-1/report.json">真实计时与用量</a></p></section>
<section><h2>JSON公式：保留内容，避免明确的定界符转义失败</h2><p>八份真实审核返回中，有两份在JSON字符串里直接写了<code>\(</code>、<code>\)</code>，严格JSON解码失败。新兼容只在这种明确错误出现时，按字符串和反斜线奇偶把四种公式定界符<code>\( \) \[ \]</code>转为合法JSON表示；解码后的反斜线、公式、问题和结论仍保留。</p><p>其他非法转义、缺失括号、截断、原始控制字符和字段类型错误不猜补；有效JSON仍走原来的严格解析，之后照常校验结构。不会把passed=false改成true，也不会补造答案。普通LaTeX命令的歧义不在本次兼容范围内。</p><div class="notice">八份保存返回已全部在本机回放，不新增云请求。四条实际DOCX任务使用同一份保存返回，各只有一次受控草稿和一次核查，不因这两种定界符错误再请求模型。核查内容仍可能有错，格式成功不证明讲解正确。</div><p><a href="../teaching-witness-replay-20261022-2/report.json">完整解析与原生生成回放</a></p></section>
<section><h2>八份真实审核：原始错误与试验限制一起保留</h2><p>首轮的非流式计量钩子没有触发，无法据它比较token；条件例稿的“只在”措辞也有必要性歧义。第二轮修正实验后，同组保持相同资料和草稿：两版都认可明确给定a=2的合法步骤。旧版也自行检出无条件错误，新线索不能冒称模型原本一定不会发现。</p><div id="audits"></div></section>
<section><h2>四条真实软件生成链路回放：查看最后交付了什么</h2><p>以下是保存的真实审核返回经过当前程序得到的成品。旧核查返回只列问题、没给修正，软件保留待核实事项；新核查返回提供了两处替换，程序实际应用。给定条件的合法等式没有被改错；通用本机提示仍会提醒核对附加条件，即使审核passed=true也可能保留。</p><div id="native"></div><p>这是受控传输回放，不是四次新的完整AI独立写作。DOCX包与文字已重读，未渲染认证Word分页布局。没有新增习题或画像得分。</p></section>
<section><h2>最终验证与打开方式</h2><p><strong>__COUNT__项关联回归通过。</strong>新增27项代数区分与完整生成检查、27项JSON边界检查；最终生产文件指纹在测试前后相同。另有4条保存真实核查的完整生成回放与8份原始JSON回放。</p><p><a href="../algebra-witness-20261021/final-regression-20261022.xml">最终测试明细</a> · <a href="../algebra-witness-20261021/final-command-20261022.json">执行命令与生产指纹</a> · <a href="../algebra-witness-review-live-20261021-2/report.json">第二轮真实审核计量</a></p><ol><li>从托盘彻底退出旧StudyForge，双击顶部“启动最新版源码”。已安装EXE仍是旧内容，本轮没有重新打包。</li><li>照常选择资料、模式、风格和审查强度；无需为了这次改动调低推理强度。</li><li>遇到“局部代数核对提示”，先看代入和题目条件，再请导师核对。它不是已确认错误，也不据此给你扣分。</li></ol><p>我的判断：继续优化应优先检查模型实际收到的原文、具体例子是否成立、必要步骤是否讲完，再用对照评估提示词。增加规则、轮次或删减内容都不能自动保证教学更好。本轮没有新增固定模型审查轮次。</p></section>
<script src="../../web/vendor/marked.js"></script><script src="../../web/vendor/purify.js"></script><script src="../../web/vendor/katex.js"></script><script src="../../web/lesson_render.js"></script><script type="application/json" id="data">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),picker=document.getElementById('pair');
for(const [i,item]of data.pairs.entries()){const option=document.createElement('option');option.value=i;option.textContent=item.title;picker.append(option)}
function text(tag,value,className){const el=document.createElement(tag);el.textContent=value;if(className)el.className=className;return el}
function link(href,label){const el=text('a',label);el.href=href;return el}
function show(){const item=data.pairs[Number(picker.value)||0];document.getElementById('question').textContent=item.question;document.getElementById('quote').textContent=item.quote;document.getElementById('manual').textContent=item.review;const host=document.getElementById('pairRows');host.replaceChildren();for(const row of item.rows){const card=text('article','', 'card'),answer=text('div','', 'answer');answer.dataset.raw=row.answer;renderLessonText(answer,row.answer);card.append(text('h3',row.arm==='baseline'?'原教学规则':'候选：未采用'),text('p',row.seconds+'秒 · 输入'+row.prompt_tokens+'／总'+row.total_tokens+' token','badge'),answer,link(row.file,'打开原样回答'),text('span',' · '),link(row.request,'实际请求'));host.append(card)}}picker.onchange=show;show();
for(const item of data.audits){const card=text('details','', 'audit-card');card.append(text('summary',item.title+' · '+item.seconds+'秒 · 原JSON'+(item.strict_json?'可解析':'转义失败')));card.append(text('p',item.note),text('p','原记录：'+(item.error||'JSON结构通过')+'；保留内容后passed='+item.passed+'，问题数'+item.issue_count));const raw=text('pre',item.raw,'raw');raw.dataset.raw=item.raw;card.append(raw,link(item.raw_file,'原始返回文件'));document.getElementById('audits').append(card)}
for(const item of data.native){const card=text('details','', 'audit-card');card.append(text('summary',item.title));const body=text('div','', 'native');body.dataset.raw=item.content;renderLessonText(body,item.content);card.append(text('p',item.note),body,link(item.file,'下载实际回放Word'));document.getElementById('native').append(card)}
function demo(){const a=Number(document.getElementById('a').value),b=Number(document.getElementById('b').value);document.getElementById('aValue').textContent=a;document.getElementById('bValue').textContent=b;document.getElementById('left').textContent=a+b;document.getElementById('right').textContent=2*a+b-2;document.getElementById('verdict').textContent=a===2?'这一次代入恰好相等，不能证明对任意a、b成立。':'两边不相等；若没有附加条件，末步不能作为一般恒等改写。'}
document.getElementById('a').oninput=demo;document.getElementById('b').oninput=demo;document.getElementById('initial').onclick=()=>{document.getElementById('a').value=2;document.getElementById('b').value=5;demo()};document.getElementById('witness').onclick=()=>{document.getElementById('a').value=3;document.getElementById('b').value=5;demo()};demo();
const demoCaption=document.querySelector('section>p');renderLessonText(demoCaption,demoCaption.textContent);
</script></body></html>'''


if __name__=='__main__':main()
