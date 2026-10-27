"""Actual teaching responses, per-question persistence and bounded speed evidence."""
import hashlib
from html import escape
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from scripts.build_teaching_witness_report import STYLE

ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/'build/homework-analysis-reuse-live-20261022-1'
REPLAY=ROOT/'build/homework-analysis-reuse-replay-20261022-2'
OUT=ROOT/'build/homework-analysis-reuse-acceptance-20261022'
TITLE='错因澄清后按题续做与完整补讲验收'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate=load(ROOT/'build/homework-analysis-reuse-20261022/final-command.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and not any(gate['tests'][key] for key in ('failure','error','skipped'))
    live={row['arm']:row for row in load(LIVE/'report.json')}
    assert all(row['status']=='completed' and len(row['calls'])==1 for row in live.values())
    analyses={arm:load(LIVE/row['analysis_file']) for arm,row in live.items()}
    replay={phase:load(REPLAY/phase/'report.json') for phase in ('prepare','baseline','resume')}
    assert all(row['passed'] and row['prompts_match_actual_sample'] and row['external_model_requests']==0 for row in replay.values())
    assert len({row['process_id'] for row in replay.values()})==3
    assert len({row['state_sha256'] for row in replay.values()})==1
    assert analyses['fixed']['items'][1:]==analyses['initial']['items'][1:]
    assert replay['resume']['analysis']['items']==analyses['fixed']['items']
    scenario=load(LIVE/'scenario.json')
    questions=json.loads(scenario['worksheet']['questions_json']);answers=json.loads(scenario['row']['answers_json'])
    rows=[]
    for question,answer in zip(questions,answers):
        index=question['index']
        rows.append({'index':index,'title':'第'+str(index+1)+'题 · '+question['topic'],'question':question['question'],'answer':answer,
            'initial':analyses['initial']['items'][index],'baseline':analyses['baseline']['items'][index],
            'fixed':analyses['fixed']['items'][index],'reused':index in (1,2)})
    table=[]
    for arm,label in (('initial','共同的初次补讲'),('baseline','澄清后：整套重做'),('fixed','澄清后：按题续做')):
        row=live[arm];usage=row['calls'][0]['usage'];raw=load(LIVE/row['calls'][0]['raw_file'])
        table.append({'label':label,'seconds':row['seconds'],'prompt_tokens':usage['prompt_tokens'],
            'completion_tokens':usage['completion_tokens'],'total_tokens':usage['total_tokens'],
            'model_written_items':len(raw['items']),'delivered_items':len(analyses[arm]['items'])})
    stats=''.join('<tr>'+''.join('<td>'+escape(str(row[key]))+'</td>' for key in ('label','seconds','prompt_tokens','completion_tokens','total_tokens','model_written_items','delivered_items'))+'</tr>' for row in table)
    native=[]
    docx_checks=[]
    for phase in ('baseline','resume'):
        row=replay[phase];document=REPLAY/phase/row['docx_file']
        with ZipFile(document) as archive:root=ET.fromstring(archive.read('word/document.xml'))
        math_nodes=len(root.findall('.//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath'))
        assert math_nodes>0
        docx_checks.append({'phase':phase,'native_math_nodes':math_nodes,'xml_parsed':True,
            'sha256':hashlib.sha256(document.read_bytes()).hexdigest()})
        native.append({'title':'旧版整套重做回放' if phase=='baseline' else '新版逐题续做回放',
            'content':row['content'],'docx':'../'+REPLAY.name+'/'+phase+'/'+row['docx_file']})
    raw=[]
    for arm in ('initial','baseline','fixed'):
        file=live[arm]['calls'][0]['raw_file']
        raw.append({'title':{'initial':'初次模型撰写3题','baseline':'旧版再次撰写3题','fixed':'新版本轮只撰写第1题'}[arm],
            'content':(LIVE/file).read_text(encoding='utf-8'),'file':'../'+LIVE.name+'/'+file,
            'request':'../'+LIVE.name+'/'+live[arm]['calls'][0]['file']})
    payload=json.dumps({'questions':rows,'native':native,'raw':raw},ensure_ascii=False).replace('<',r'\u003c')
    html=TEMPLATE.replace('__STYLE__',STYLE).replace('__PAYLOAD__',payload).replace('__STATS__',stats).replace('__TESTS__',str(gate['tests']['total']))
    OUT.mkdir(exist_ok=True,parents=True);(OUT/(TITLE+'.html')).write_text(html,encoding='utf-8')
    manifest={'date':'2026-10-22','regression':gate['tests'],'source_sha256':gate['production_after'],'mobile_shell':66,
        'actual_model_requests':3,'actual_samples_scope':'one synthetic submitted worksheet; fixed supplied grade, no new grading-quality test',
        'controlled_replay_requests':3,'separate_processes':3,'persistent_reused_questions':[1,2],'word_exports':2,'docx_structure_checks':docx_checks,
        'new_fixed_model_rounds':0,'phone_authenticated_api_test':True,'physical_android_test':False,
        'new_business_ui_test':False,'docx_layout_rendered':False,'packaged':False,
        'manual_review':[
            '初次回答能区分只有结果4与可定位的推理步骤，Q0保持不确定；另两题使用已提供的自报，不将历史疑问当成当前能力结论。',
            '两版数学补讲均解释减3后为何仍需除以2，并用代回与逆运算核对；不认定新版数学内容必然优于旧版。',
            '新版补讲的clarification仍重复询问已经自报的步骤；该字段未成为新的强制问卷，原返回保留。',
            '保留的高斯补讲主线及立方体通量正确，但“积分核”称谓可更准确；复用也会保留既有措辞问题，不是自动纠错机制。',
            '提速只来自本次澄清后的补讲组件。没有测试完整出题、初次评分、长资料生成或全软件RAM。',
        ]}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUT/(TITLE+'.html'))


TEMPLATE=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>错因澄清后按题续做与完整补讲验收</title><link rel="stylesheet" href="../../web/vendor/katex.css"><style>__STYLE__ .scroll{overflow-x:auto}.lesson,.raw{max-height:650px;overflow:auto;overflow-wrap:anywhere}.lesson{padding-right:8px;scrollbar-gutter:stable}.raw{white-space:pre-wrap}.flow{display:flex;gap:8px;flex-wrap:wrap}.flow span{padding:8px 12px;background:#edf3e9;border-radius:10px}.metric{font-size:28px;font-weight:700}.katex-display{overflow-x:auto;overflow-y:hidden}.native{max-height:750px;overflow:auto}.audit-card{border:1px solid #d7e3d6;border-radius:16px;padding:18px;margin:14px 0}select{display:block;max-width:100%}code{overflow-wrap:anywhere}</style></head><body>
<header><span class="badge">STUDYFORGE · 2026-10-22 · 补讲一致性</span><h1>澄清一题，更新一题；完整讲解仍然交付</h1><p>原流程会因一题的新问卷重做整套失分题。本轮保留有完整依据记录的已完成补讲，只处理相关自报或依据改变的部分，减少等待与无关改写。真实对照中保留的两题逐字相同。</p><p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../docs/错因澄清后按题续做验收.md">实施与限制</a> · <a href="../../web/help/guide.html#homework">软件内指南</a> · <a href="manifest.json">完整证据清单</a></p><div class="notice">本轮源码未打包。界面沿用原入口，电脑和手机共用后端；手机公共壳v66同步指南。分题复用不是再做一次测验，也不证明旧补讲一定正确。</div></header>
<section><h2>一次问卷之后，流程具体有什么变化</h2><div class="flow"><span>初次评分与补讲</span><span>第1题原因待确认</span><span>填写这一题的思路</span><span>更新1题＋保留2题</span><span>交付含全部题目的文档</span></div><p>只写“4”不能据此判断学生在哪一步出错；自报“做完7−3得到4，忘记除以2”后，导师再围绕这一步解释。另两题已有作答与自报依据，没有因第1题澄清而重新定性。</p><ul><li>缓存绑定本次提交、项目、对话、题目／参考解、作答、评分、教学设置、相关画像快照、实际模型与规则。</li><li>每道题还绑定自身的问卷内容，以及此前讲解的实际指纹；修改或损坏的记录重新处理。</li><li>原题、参考解和本次完整作答继续进入模型上下文，避免裁掉跨题依赖；只限定本轮输出哪些题。</li><li>旧任务没有依据记录时回退重做；未知原因仍保持未知，不因“复用”自动变成确定诊断。</li></ul></section>
<section><h2>同一份实际返回：逐题看原文与最终补讲</h2><label for="question">选择题目</label><select id="question"></select><p id="original"></p><blockquote id="answer"></blockquote><p id="comparisonNote" class="notice"></p><div id="comparison" class="columns"></div><p>示例为独立测试数据，分数已经给定；这轮不评价模型初次评分准确率。第2、3题先前已提供自报，第1题后来单独澄清。自报继续标为未独立验证，历史画像仅作线索。</p></section>
<section><h2>实际耗时与token：限定在“澄清后的补讲阶段”</h2><div class="scroll"><table><thead><tr><th>阶段</th><th>秒</th><th>输入token</th><th>输出token（含推理）</th><th>总token</th><th>模型本轮撰写题数</th><th>合并交付题数</th></tr></thead><tbody>__STATS__</tbody></table></div><p>本次后续组件约31.479→19.267秒，少约38.8%；总token为6359→4730，少约25.6%。新请求输入反而多19 token，因为明确了只输出本轮题号；节省来自少重新撰写两题，完整资料没有被缩短。</p><div class="notice">同一模型deepseek-flash、high、精学、直观与专业并重。只有一组工作表、一次配对，缓存和模型随机波动未被排除。不能承诺每次快38.8%，也不能把这段耗时当作从出题、初次评分到排版的完整任务时间；全软件内存未在本轮测量。</div><p><a href="../homework-analysis-reuse-live-20261022-1/report.json">全部实际计时与用量</a> · <a href="../homework-analysis-reuse-live-20261022-1/scenario.json">相同题目、作答、自报与画像</a></p></section>
<section><h2>三份原始模型返回：可核对本轮到底写了几题</h2><p>完整保留原始JSON和实际请求。新版最终有3题，不表示模型又写了3题；其中2题由软件从已保存结果原样合并。没有隐藏推理文本或凭据。</p><div id="raw"></div></section>
<section><h2>独立进程续做与两份Word</h2><p>分别启动三个独立Python进程：保存初次结果、回放旧版、回放新版。新版重新读取同一保存状态，只请求第1题；三阶段状态文件指纹相同，初次与续做提示逐字对应前述真实请求，不新增云调用。</p><div id="native"></div><p><a href="../homework-analysis-reuse-replay-20261022-2/prepare/report.json">第一次保存记录</a> · <a href="../homework-analysis-reuse-replay-20261022-2/resume/report.json">新进程续做记录</a></p><p>Word通过应用自身的批改文档生成器导出，原题及普通正文已重读；公式转成原生OMML，不能用Markdown源码是否原样出现在XML来判定导出失败。本轮未渲染认证Word分页布局。</p></section>
<section><h2>最终验收与剩余问题</h2><p><strong>__TESTS__项关联回归通过。</strong>覆盖逐题复用、身份与设置改变、损坏／旧记录回退、作业与评分、暂停恢复、教学画像、修复练习，以及受信手机API。最终生产文件在回归前后指纹相同。</p><p>完整提交与问卷原生流程确认：先得到解析、未知错因等待、回答后继续、原评分不重复写入，最终Word包含全部题目。受信手机接口也实际完成两题提交、单题澄清和完整Word下载；这不是实体安卓或手机UI触控验收。</p><p>保留内容也会保留先前错误。样例高斯补讲的“积分核”称谓可更准确；新版数学返回还重复询问已经自报的步骤，虽未成为强制新问卷，仍不够利落。主线计算与逆运算解释两版均正确，不宣称所有教学质量已经胜出。</p><p><a href="../homework-analysis-reuse-20261022/final-regression.xml">最终测试明细</a> · <a href="../homework-analysis-reuse-20261022/final-command.json">命令与冻结指纹</a> · <a href="../homework-analysis-reuse-20261022/phone-native.xml">受信手机接口单项验证</a> · <a href="../homework-analysis-reuse-20261022/baseline.xml">旧版复现与新契约检查</a></p><p>旧版28项新检查有25失败、3通过，其中多项因尚不存在新记录字段而失败，不能解释成25个独立旧缺陷。新增完整流程和手机接口后，针对性文件共30项。早期旧跨题夹具依赖“重写整套题”，已明确改为模拟缺记录的历史任务；仍核验他题引句不能充当本题错因。</p><p>权限收紧后首次测试在沙箱临时目录产生53项初始化错误，改用工作区临时目录后53项通过；这是测试环境问题。首次Word回放把原生公式当作应保留的LaTeX源码，已改为核验正文及公式结构后重跑，不计为产品修复。</p></section>
<section><h2>实际使用</h2><ol><li>从托盘彻底退出旧StudyForge，双击顶部“启动最新版源码”。已安装EXE没有改变。</li><li>照常完整提交题单；若收到错因问卷，填写当时的真实步骤。无需开新开关。</li><li>进度会提示保留了几题、正在处理哪几题。完成后仍下载一份包含全部原题、作答、评分与补讲的文档。</li><li>手机连接这一电脑实例后刷新页面，使用公共壳v66。旧任务若缺记录，第一次仍可能完整重做。</li></ol></section>
<script src="../../web/vendor/marked.js"></script><script src="../../web/vendor/purify.js"></script><script src="../../web/vendor/katex.js"></script><script src="../../web/lesson_render.js"></script><script type="application/json" id="data">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),picker=document.getElementById('question');
function node(tag,value,cls){const el=document.createElement(tag);if(value)el.textContent=value;if(cls)el.className=cls;return el}
function link(path,label){const el=node('a',label);el.href=path;return el}
function lesson(item){return '### 错因与证据边界\n'+item.cause+'\n\n### 针对性讲解\n'+item.explanation+'\n\n### 核对方法\n'+item.check}
data.questions.forEach((item,index)=>{const option=node('option',item.title);option.value=index;picker.append(option)});
function show(){const item=data.questions[Number(picker.value)||0];document.getElementById('original').textContent=item.question;document.getElementById('answer').textContent='本次作答：'+item.answer;document.getElementById('comparisonNote').textContent=item.reused?'新版这题与初次结果逐字相同，没有再次请求模型撰写。':'这题收到新自报，旧／新都重新补讲；新版只处理这一题。';const host=document.getElementById('comparison');host.replaceChildren();for(const arm of ['baseline','fixed']){const card=node('article','', 'card'),body=node('div','', 'lesson'),raw=lesson(item[arm]);body.dataset.raw=raw;renderLessonText(body,raw);card.append(node('h3',arm==='baseline'?'旧流程：整套重做':'新流程：'+(item.reused?'保留初次补讲':'更新本题')),node('p','证据状态：'+item[arm].confidence,'badge'),body);host.append(card)}}picker.onchange=show;show();
for(const item of data.raw){const details=node('details','', 'audit-card'),raw=node('pre',item.content,'raw');raw.dataset.raw=item.content;details.append(node('summary',item.title),raw,link(item.file,'打开原始返回'),node('span',' · '),link(item.request,'实际请求'));document.getElementById('raw').append(details)}
for(const item of data.native){const details=node('details','', 'audit-card'),body=node('div','', 'native');body.dataset.raw=item.content;renderLessonText(body,item.content);details.append(node('summary',item.title),body,link(item.docx,'下载实际Word'));document.getElementById('native').append(details)}
</script></body></html>'''


if __name__=='__main__':main()
