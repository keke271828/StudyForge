"""Bounded automatic background, unchanged manual choices and honest live results."""
import hashlib
from html import escape
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from scripts.build_library_followup_report import TEMPLATE as PREVIOUS_TEMPLATE

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'build/library-auto-context-20261021'
LIVE=ROOT/'build/library-auto-context-live-20261021-1'
OUT=ROOT/'build/library-auto-context-acceptance-20261021'
TITLE='知识库自动参考与讲解聚焦验收'
REVIEWS={
 'gauss':'两版都正确区分净通量与局部电场，并逐面计算立方体通量，不能说旧版原本不会答。新版背景只保留高斯节点，回答没有混入极限或因果内容，但仍将大带电板产生均匀场的理想化条件说得不够明确，未给逐条来源位置。',
 'causal':'两版都通过高／低动机的分组构造，算出78与62的16分混杂反例。旧版明确给出合并标准差约11.66，新版用表格且将标准误简写为约0.16。新版开头把“大样本和统计显著”并称为压缩误差，措辞仍不准确：减少抽样误差的是样本量等设计因素，显著性是检验结果。新版更慢且总token更多，不宣称全面质量或成本优势。'}
TITLES={'math':'手动引用：极限唯一性','gauss':'自动参考：高斯定律','causal':'自动参考：因果识别'}


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    old=load(BASE/'baseline/requests.json');new=load(BASE/'fixed-final/requests.json')
    assert new==load(BASE/'fixed/requests.json'),'Final source must reproduce the live experiment input.'
    assert old[0]['messages']==new[0]['messages'],'Manual-reference positive control must stay identical.'
    ui=load(ROOT/'build/library-auto-context-ui-20261021-1/ui-report.json')
    local=load(ROOT/'build/library-auto-context-local-20261021-1/report.json')
    tests=ET.parse(BASE/'final-regression.xml').getroot().findall('.//testcase')
    baseline=ET.parse(BASE/'baseline-corrected.xml').getroot().findall('.//testcase')
    assert ui['passed'] and local['passed'] and tests and all(t.find(k) is None for t in tests for k in ('failure','error','skipped'))
    sources=[]
    for before,after in zip(old,new):
        assert before['name']==after['name'] and before['original_reached_model'] and after['original_reached_model']
        rows=[]
        for phase,row in (('baseline',before),('fixed',after)):
            receipt=row['receipt'];assert hashlib.sha256(row['context'].encode()).hexdigest()==receipt['context_sha256']
            rows.append({'phase':phase,'context':row['context'],'characters':len(row['context']),
                         'titles':[source['title'] for source in receipt['sources']]})
        sources.append({'name':before['name'],'title':TITLES[before['name']],'question':before['question'],
                        'quote':before['quote'],'rows':rows,'same_messages':before['messages']==after['messages']})
    live={(row['case'],row['phase']):row for row in load(LIVE/'report.json')};answers=[];timings=[]
    for name in ('gauss','causal'):
        rows=[]
        for phase in ('baseline','fixed'):
            result=live[name,phase];assert result['status']=='completed' and len(result['calls'])==1
            request=load(LIVE/result['calls'][0]['file']);expected=next(row for row in (old if phase=='baseline' else new) if row['name']==name)
            assert request['messages'][-1]==expected['messages'][-1]
            assert request['messages'][0]['content'].startswith(expected['messages'][0]['content'])
            usage=result['calls'][0]['usage']
            rows.append({'phase':phase,'answer':(LIVE/result['answer_file']).read_text(encoding='utf-8'),
                         'file':result['answer_file'],'seconds':result['seconds'],
                         'prompt_tokens':usage['prompt_tokens'],'total_tokens':usage['total_tokens']})
        answers.append({'name':name,'title':TITLES[name],'review':REVIEWS[name],'rows':rows})
        timings.append('<tr><td>'+escape(TITLES[name])+'</td><td>'+str(rows[0]['prompt_tokens'])+' → '+str(rows[1]['prompt_tokens'])+'</td><td>'+str(rows[0]['seconds'])+' → '+str(rows[1]['seconds'])+'秒</td><td>'+str(rows[0]['total_tokens'])+' → '+str(rows[1]['total_tokens'])+'</td></tr>')
    checks=''.join('<li>'+escape(value)+'</li>' for value in ui['checks'])
    local_rows=''.join('<tr><td>'+escape(row['query'])+'</td><td>'+escape('、'.join(row['baseline']['titles']) or '未自动采用')+'</td><td>'+escape('、'.join(row['fixed']['titles']) or '未自动采用')+'</td></tr>' for row in local['queries'])
    payload=json.dumps({'sources':sources,'answers':answers},ensure_ascii=False).replace('<','\\u003c')
    style=PREVIOUS_TEMPLATE.split('<style>',1)[1].split('</style>',1)[0]
    html=TEMPLATE
    for key,value in {'STYLE':style,'COUNT':str(len(tests)),'CHECKS':checks,'UI_COUNT':str(len(ui['checks'])),
                     'TIMINGS':''.join(timings),'LOCAL_ROWS':local_rows,'PAYLOAD':payload}.items():html=html.replace('__'+key+'__',value)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/(TITLE+'.html')).write_text(html,encoding='utf-8')
    (OUT/'manual-review.json').write_text(json.dumps(REVIEWS,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({'python_checks':len(tests),'new_focused_checks':28,
        'baseline_failures':sum(t.find('failure') is not None for t in baseline),'node_syntax_checks':4,
        'ui_checks':len(ui['checks']),'controlled_ui_model_calls':ui['controlled_model_requests'],
        'actual_cloud_model_calls':4,'local_e5_queries':7,'new_ocr_pages':0,'fixed_rounds_added':0,
        'source_context_characters':{row['name']:[r['characters'] for r in row['rows']] for row in sources},
        'physical_android_test':False,'packaged':False,'mobile_shell':65},ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUT/(TITLE+'.html'))


TEMPLATE=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>知识库自动参考与讲解聚焦验收</title><link rel="stylesheet" href="../../web/vendor/katex.css"><style>__STYLE__ .metric{font-size:24px;font-weight:650}.card h3{margin-top:0}.source{max-height:540px}.lesson{max-height:800px}</style></head><body>
<header><span class="badge">STUDYFORGE · 2026-10-21 · 自动参考筛选</span><h1>让相关原文进入讲解，减少无关章节干扰</h1><p>“成立、具体例子”等教学措辞会命中许多学科；只命中书名，也不代表同一本书的每章都相关。本轮把完整搜索与自动加入对话分开，保留手动选择，并优先用具体概念定位定义和条件页。</p><p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../web/help/guide.html#library">软件内使用指南</a> · <a href="../../docs/知识库自动参考与讲解聚焦验收.md">完整实施记录</a></p><div class="notice">这是本机筛选规则，不是语义正确性的认证。没有新增长期后台通读、固定云端审查或索引重建；手动节点、未读授权、对话隔离保持。以下保留四份真实回答及残余问题，不宣称所有讲解更快或更好。</div></header>
<section><h2>同一问题、语料与范围：三组实际参考输入</h2><div class="controls"><label for="sourceCase">选择场景</label><select id="sourceCase"></select></div><h3 id="sourceTitle"></h3><p id="sourceQuestion"></p><blockquote id="sourceQuote"></blockquote><p id="sourceNote" class="notice"></p><div id="sourceComparison" class="columns"></div><p class="subtle">来自真正的聊天准备链路；原始参考文字未让AI改写。资料为独立受控保存文本，不是三本教材通读。原文、AI图像记录和导航笔记的身份标记保持。数学手动引用的完整请求逐字相同，是保留用户选择的正向对照。</p><p><a href="../library-auto-context-20261021/baseline/requests.json">原生修复前输入</a> · <a href="../library-auto-context-20261021/fixed-final/requests.json">最终原生输入</a> · <a href="../library-auto-context-20261021/baseline-functions/manifest.json">修复前函数指纹</a></p></section>
<section><h2>四份真实DeepSeek讲解：没有润色</h2><label for="answerCase">选择问题</label> <select id="answerCase"></select><p id="answerReview" class="notice"></p><div id="answerComparison" class="columns"></div><p class="subtle">请求模型名deepseek-flash / high；精学模式、直观与专业并重。使用原生聊天准备出的同一提问及旧AI原句，再由同一客户端请求真实服务；实验重放不执行工具、不联网。最终代码重建的三份原生输入与本轮真实实验所用输入逐字一致。</p><div class="scroll"><table class="timing"><thead><tr><th>场景</th><th>输入token</th><th>实际总耗时</th><th>总token</th></tr></thead><tbody>__TIMINGS__</tbody></table></div><p>高斯样例输入少453 token，本次采样更快；因果样例输入少294 token，但推理更长，最终更慢且总token更多。背景减少不等于总成本或总耗时必然减少，不能承诺普遍30%提速。教师规则、模型、推理强度与固定请求轮数没有更换。</p><p><a href="../library-auto-context-live-20261021-1/report.json">实际耗时、token与请求体指纹</a> · <a href="manual-review.json">逐组人工评价</a></p></section>
<section><h2>自动参考现在怎样选择</h2><ul><li>节点标题、原页／OCR、保存的AI图像记录、未标疑的导航笔记中有具体概念线索，或有达到现有阈值的语义线索，才作为自动候选。</li><li>仅书名或教学措辞命中仍出现在完整搜索结果，显示“此命中不自动加入对话，可手动选用”；你明确引用的节点始终保留。</li><li>筛选在候选数量上限之前完成，避免前六个弱结果挤掉真正目标。原页选择也优先考虑知识线索，保留相邻定义／条件页。</li><li>仅有“这里为什么”等措辞且没有概念线索的自动查询，直接跳过全库笔记和本地模型扫描；已手动选定的原文照常提供。</li><li>数学、哲学、社会科学及跨领域反馈机制仍可检索；不会为了聚焦强制只留一个章节，也不把物理视为所有学科的默认解释。</li></ul><div class="notice">这是有限词表与已有语义阈值组成的启发式规则，仍可能误收或漏收；原文进入输入，也不保证模型用对。临界或专门术语可通过搜索后手动引用。未读章节仍只有位置提示，不把目录命中当成已经阅读。</div></section>
<section><h2>真实本地E5模型：同语料七个查询</h2><p>使用已安装、固定版本的多语言E5模型，不下载、不重建索引、不新增OCR或云请求。旧版自动采用的3个目标在新版仍保留，其中反馈机制查询减少1个无关社会科学节点；另外2个改写问题旧、新都未达到自动采用条件，不把它们算成成功自动命中。两条纯教学措辞均未自动加入书库内容。</p><div class="scroll"><table class="timing"><thead><tr><th>实际查询</th><th>旧版自动参考</th><th>新版自动参考</th></tr></thead><tbody>__LOCAL_ROWS__</tbody></table></div><p><a href="../library-auto-context-local-20261021-1/report.json">完整同模型比较</a></p></section>
<section><h2>最终回归与电脑／手机验收</h2><p><strong>__COUNT__项关联Python检查通过，含本轮28项针对性检查；4项Node语法检查通过。</strong>修复前18项有效复现中8项失败、10项通过；其后新增命名概念、远处定义页和跳过无效全库扫描的边界检查。</p><p>实际电脑和经设备审批的HTTPS手机页面完成__UI_COUNT__项检查，4次受控模型请求、0次外部模型请求。选择弱命中后，两端导师确实收到指定原文；自动参考只保留相关节点，无关未读兄弟目录未混入。控制台错误0项，390／320像素无横向溢出。不是实体安卓触控或跨网稳定性认证。</p><details><summary>展开__UI_COUNT__项实际操作</summary><ul>__CHECKS__</ul></details><div class="shots"><a href="../library-auto-context-ui-20261021-1/desktop-weak-search.png"><img src="../library-auto-context-ui-20261021-1/desktop-weak-search.png" alt="电脑完整搜索保留弱命中和手动选择"></a><a href="../library-auto-context-ui-20261021-1/phone-weak-search-320.png"><img src="../library-auto-context-ui-20261021-1/phone-weak-search-320.png" alt="配对手机显示弱命中与手动入口"></a></div><p><a href="../library-auto-context-20261021/baseline-corrected.xml">有效问题复现</a> · <a href="../library-auto-context-20261021/final-regression.xml">最终回归</a> · <a href="../library-auto-context-ui-20261021-1/ui-report.json">完整两端操作</a></p></section>
<section><h2>打开与验收</h2><ol><li>在系统托盘彻底退出旧StudyForge，再双击上方“启动最新版源码”；本轮未打包，已安装EXE不会自动变更。</li><li>工作台使用“自动找相关已读节点”，选中导师原句后追问；在检索记录中核对实际背景章节。</li><li>只按书名或通用措辞搜索时，仍能看到弱命中说明。需要时点开已读章节，再“引用到当前对话”，你的明确选择优先保留。</li><li>手机连接同一源码实例并刷新，公共壳v65。手动引用、原页和画像分数保持各自原有边界。</li></ol><p>这轮减少的是不必要参考和无效自动扫描，没有证明全软件RSS、长视频速度或全部教学质量已经解决。少量合成语料与四次真实请求也不足以估计全书库准确率。</p></section>
<script src="../../web/vendor/marked.js"></script><script src="../../web/vendor/purify.js"></script><script src="../../web/vendor/katex.js"></script><script src="../../web/lesson_render.js"></script><script type="application/json" id="data">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),sourceCase=document.getElementById('sourceCase'),answerCase=document.getElementById('answerCase');
for(const [list,picker]of [[data.sources,sourceCase],[data.answers,answerCase]])list.forEach((item,index)=>{const option=document.createElement('option');option.value=index;option.textContent=item.title;picker.append(option);});
function showSources(){const item=data.sources[Number(sourceCase.value)||0];document.getElementById('sourceTitle').textContent=item.title;document.getElementById('sourceQuestion').textContent=item.question;document.getElementById('sourceQuote').textContent=item.quote;document.getElementById('sourceNote').textContent=item.same_messages?'用户明确选择的手动节点：修复前后完整消息逐字相同。':'自动参考：目标原文保持，减少只因通用措辞命中的背景。';const host=document.getElementById('sourceComparison');host.replaceChildren();for(const row of item.rows){const card=document.createElement('article');card.className='card '+(row.phase==='fixed'?'new':'old');const title=document.createElement('h3');title.textContent=row.phase==='fixed'?'修复后实际参考':'修复前实际参考';const metric=document.createElement('p');metric.className='metric';metric.textContent=row.titles.length+'个节点 · '+row.characters+'字符';const names=document.createElement('p');names.textContent=row.titles.join('；');const text=document.createElement('pre');text.className='source';text.dataset.raw=row.context;text.textContent=row.context;card.append(title,metric,names,text);host.append(card);}}
function showAnswers(){const item=data.answers[Number(answerCase.value)||0];document.getElementById('answerReview').textContent=item.review;const host=document.getElementById('answerComparison');host.replaceChildren();for(const row of item.rows){const card=document.createElement('article');card.className='card '+(row.phase==='fixed'?'new':'old');const title=document.createElement('h3');title.textContent=row.phase==='fixed'?'新版真实采样':'旧版真实采样';const metric=document.createElement('p');metric.className='badge';metric.textContent=row.seconds+'秒 · 输入'+row.prompt_tokens+' token';const body=document.createElement('div');body.className='lesson';body.dataset.raw=row.answer;renderLessonText(body,row.answer);const link=document.createElement('a');link.href='../library-auto-context-live-20261021-1/'+row.file;link.textContent='打开原样最终回答';card.append(title,metric,body,link);host.append(card);}}
sourceCase.onchange=showSources;answerCase.onchange=showAnswers;showSources();showAnswers();
</script></body></html>'''


if __name__=='__main__':main()
