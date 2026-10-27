"""Preserve six actual answers, positive controls, source inputs and limits."""
import hashlib
from html import escape
import json
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'build/library-followup-20261021'
LIVE=ROOT/'build/library-followup-live-20261021-1'
UI=ROOT/'build/library-followup-ui-20261021-1'
OUT=ROOT/'build/library-followup-acceptance-20261021'
TITLE='原句追问与知识库教学对照验收'
REVIEWS={
 'math':'两份都正确指出取半径的选择不唯一，并计算了1/3的反例。这组旧／新实际请求体逐字相同，回答措辞和耗时的差别只能视为重复采样波动，不能归功于修复。新版n≥N的写法也应与所选门槛定义保持一致。',
 'gauss':'旧版虽然没有收到这份高斯原文，仍自行给出了有效的正负电荷反例，不能说它原本不会答。新版收到原文后采用立方体逐面通量计算，和该卡点更直接对应。残余问题：把被积函数简写成E不够严格；最后谈散度为零时应明确它需要局部无电荷等额外前提，而非由总电荷零直接推出。',
 'causal':'两版都给出了可跟算的12分混杂反例；新版篇幅较短，相关书库节点排在前面。两份标准误算例的组内方差口径、是否条件于固定分组构成没有交代清楚，不能把这些额外数值当作严格统计核验通过。'}
TITLES={'math':'数学：半径为什么可以取1/3','gauss':'物理：净通量零为何不等于场零','causal':'社会科学：大样本为何不能替代因果设计'}


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    requests={phase:{row['name']:row for row in load(BASE/phase/'requests.json')} for phase in ('baseline','fixed')}
    live={(row['case'],row['phase']):row for row in load(LIVE/'report.json')}
    ui=load(UI/'ui-report.json');tests=ET.parse(BASE/'final-regression.xml').getroot().findall('.//testcase')
    assert ui['passed'] and tests and all(t.find(k) is None for t in tests for k in ('failure','error','skipped'))
    payload=[];timings=[];reviews=[]
    for name in TITLES:
        rows=[];hashes=[]
        for phase in ('baseline','fixed'):
            request=requests[phase][name];result=live[name,phase];assert result['status']=='completed' and len(result['calls'])==1
            body=load(LIVE/result['calls'][0]['file']);assert body['model']=='deepseek-flash'
            assert body['messages'][-1]==request['messages'][-1] and body['messages'][0]['content'].startswith(request['messages'][0]['content'])
            hashes.append(result['calls'][0]['sha256'])
            receipt=request['receipt'];context=''
            if receipt:
                system=request['messages'][0]['content'];start=system.index('\n## 全局书库参考')
                context=system[start:start+receipt['context_characters']]
                assert hashlib.sha256(context.encode()).hexdigest()==receipt['context_sha256']
            usage=result['calls'][0].get('usage',{})
            rows.append({'phase':phase,'answer':(LIVE/result['answer_file']).read_text(encoding='utf-8'),'context':context,
                'original_reached_model':request['original_reached_model'],'receipt':receipt,'seconds':result['seconds'],
                'prompt_tokens':usage.get('prompt_tokens'),'answer_file':result['answer_file']})
        payload.append({'name':name,'title':TITLES[name],'review':REVIEWS[name],'question':requests['fixed'][name]['question'],
            'quote':requests['fixed'][name]['quote'],'original':requests['fixed'][name]['original'],'same_request_body':hashes[0]==hashes[1],'rows':rows})
        timings.append('<tr><td>'+escape(TITLES[name])+'</td><td>'+str(rows[0]['seconds'])+'秒</td><td>'+str(rows[1]['seconds'])+'秒</td><td>'+str(rows[0]['prompt_tokens'])+' → '+str(rows[1]['prompt_tokens'])+'</td><td>'+('逐字相同' if hashes[0]==hashes[1] else '书库参考改变')+'</td></tr>')
        reviews.append({'case':name,'same_actual_request':hashes[0]==hashes[1],'review':REVIEWS[name]})
    assert payload[0]['same_request_body']
    data=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')
    html=TEMPLATE.replace('__DATA__',data).replace('__COUNT__',str(len(tests))).replace('__TIMINGS__',''.join(timings))
    html=html.replace('__CHECKS__',''.join('<li>'+escape(check)+'</li>' for check in ui['checks']))
    OUT.mkdir(parents=True,exist_ok=True);(OUT/(TITLE+'.html')).write_text(html,encoding='utf-8')
    (OUT/'manual-review.json').write_text(json.dumps(reviews,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({'python_checks':len(tests),'focused_checks':14,'node_syntax_checks':4,
        'ui_checks':len(ui['checks']),'actual_model_requests':6,'same_input_positive_control':'math',
        'model':'deepseek-flash','effort':'high','browsing':False,'tools_in_live_replay':False,
        'reading_corpus':'synthetic controlled saved text','physical_android_test':False,'packaged':False,'mobile_shell':64},ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUT/(TITLE+'.html'))


TEMPLATE=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>原句追问与知识库教学对照验收</title><link rel="stylesheet" href="../../web/vendor/katex.css">
<style>:root{font:16px/1.85 system-ui,"Microsoft YaHei",sans-serif;color:#263f36;background:#eef1e8}*{box-sizing:border-box}body{max-width:1320px;margin:auto;padding:24px 20px}header,section{background:#fffefa;border:1px solid #c7d5c7;padding:25px;border-radius:18px;margin:20px 0;min-width:0}h1{font-size:31px;line-height:1.45}h2{font-size:23px}h3{font-size:18px}a{color:#14694e;overflow-wrap:anywhere}.badge{display:inline-block;border-radius:18px;background:#e2ecdd;font-size:13px;padding:5px 12px}.notice{padding:14px 17px;background:#fff1d6;border-left:4px solid #af8c4d;border-radius:6px}.subtle{font-size:13px;color:#54695b}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center}select{font:inherit;color:inherit;border:1px solid #a8bfa9;padding:9px 12px;background:#edf5e8;border-radius:9px;max-width:100%}select:focus-visible,summary:focus-visible{outline:3px solid #4a9377;outline-offset:3px}.columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px;margin-top:20px}.card{padding:19px;border:1px solid #cbd7c5;border-radius:13px;min-width:0}.card h3{margin-top:0}.old{border-top:4px solid #b89a63}.new{border-top:4px solid #578869}.lesson{line-height:1.95;overflow-wrap:anywhere;max-height:850px;overflow:auto;padding-right:8px}.lesson .katex-display{overflow-x:auto;overflow-y:hidden}.lesson table{display:block;max-width:100%;overflow:auto;border-collapse:collapse}.lesson td,.lesson th{border:1px solid #c7d3c2;padding:7px}.source{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.85 Consolas,"Microsoft YaHei",monospace;background:#eef5e8;border:1px solid #d7e1cf;border-radius:10px;padding:12px;max-height:650px;overflow:auto}.scroll{overflow:auto}table{border-collapse:collapse;width:100%}.timing{min-width:700px}th,td{padding:10px;border:1px solid #ced8c9;text-align:left;vertical-align:top}blockquote{border-left:3px solid #95b29b;margin:15px 0;padding:12px 15px;background:#eff4e9}.shots{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:15px;align-items:start}.shots img{display:block;max-width:100%;height:auto;border:1px solid #c7d3c2;border-radius:12px}li{margin:8px 0}details{margin:15px 0}summary{cursor:pointer;font-weight:600}@media(max-width:820px){body{padding:10px}header,section{padding:16px}h1{font-size:25px}.columns,.shots{grid-template-columns:minmax(0,1fr)}.card{padding:14px}}</style></head><body>
<header><span class="badge">STUDYFORGE · 2026-10-21 · 六次真实模型对照</span><h1>“这里为什么？”现在能用所选原句查书</h1><p>修复前，针对旧AI原句追问时，书库只按当前简短提问查找。所选概念未参与，可能漏掉相关原文、也可能在手动节点中挑错页。现在用当前问题和明确引用的原句定位书库，再把实际原文作为参考。</p><p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../web/help/guide.html#library">软件内操作指南</a> · <a href="../../docs/原句追问与知识库教学对照验收.md">完整实施、验证与限制</a></p><div class="notice">旧AI原句只是检索线索，不是原文证据或新的权限指令。以下六份最终回答未经润色，仍保留模型错误或不够精确之处；本轮不更换教师提示词，不增加固定审查请求，不声称整体教学质量或速度全面胜出。</div></header>
<section><h2>切换三个领域的原样回答</h2><div class="controls"><label for="case">对照问题</label><select id="case"></select><label for="view">查看内容</label><select id="view"><option value="answer">模型最终回答</option><option value="context">实际提供的书库参考</option></select></div><h3 id="title"></h3><p>同一追问：<span id="question"></span></p><blockquote id="quote"></blockquote><details><summary>这次实际目标原文（受控保存文本）</summary><pre id="original" class="source"></pre></details><p id="review" class="notice"></p><p id="control" class="subtle"></p><div class="columns" id="comparison"></div><p class="subtle">三组均使用deepseek-flash / high，深度学习模式、直观与专业并重风格；对照来自软件实际聊天准备链路，再由同一客户端请求真实服务。实验重放不执行工具、不联网，不测试真实云模型自主查书能力。书库正文为独立受控保存文本，不是三本教材的完整通读。</p></section>
<section><h2>实际耗时与输入：不据单次采样认证提速</h2><div class="scroll"><table class="timing"><thead><tr><th>问题</th><th>修复前采样</th><th>修复后采样</th><th>服务报告输入token</th><th>请求比较</th></tr></thead><tbody>__TIMINGS__</tbody></table></div><p>这三组新版采样都更快，但数学组的实际请求体逐字相同，仍出现明显耗时和回答差异。因此这些时间包含生成波动、推理长度、缓存和服务等待，不能归因为这次代码修复，不能用来承诺30%提速。高斯组多提供了目标原文，服务报告输入增加180 token；没有多发一次固定模型请求。</p><p><a href="../library-followup-live-20261021-1/report.json">六次真实请求时间、token与请求体指纹</a> · <a href="../library-followup-20261021/baseline/requests.json">原生准备链路：修复前</a> · <a href="../library-followup-20261021/fixed/requests.json">原生准备链路：修复后</a> · <a href="manual-review.json">逐组人工评价</a></p></section>
<section><h2>讲解生成与权限边界</h2><ul><li>电脑和手机共用修复后的聊天链路。手动模式只在已选节点内找原页；关闭书库或不引用资料时不会因选中原句而重开权限。</li><li>未读节点仍只提供目录候选，不读取未授权正文。原句中的“只依据原文”等旧AI文字不作为新的范围命令。</li><li>没有新增生成说明时，讲解任务沿用最后一条原句追问的检索线索；新填生成说明时使用新说明，不自动复活旧原句。</li><li>检索线索随任务固定，多部分讲解整理书库参考时继续使用；实测完整多部分DOCX流程保留第9页条件。</li><li>学生问题仍逐字保存，旁支上下文、消息ID和指纹不作为概念检索词。检索本身不新增画像或成绩。</li></ul></section>
<section><h2>回归与实际两端操作</h2><p><strong>__COUNT__项最终关联Python检查通过，含14项本轮针对性检查；4项Node语法检查通过。</strong>本机修复前11项针对性检查中7项失败、4项通过；后来增加3项文档衔接检查。</p><p>实际电脑和经过设备审批的HTTPS手机页面完成6项操作，2次受控模型请求、0次外部请求。选择原句、发送简短问题、显示原文依据、切换项目和刷新恢复均核对。控制台错误0项，390／320像素无横向溢出。</p><details><summary>展开六项实际操作</summary><ul>__CHECKS__</ul></details><div class="shots"><a href="../library-followup-ui-20261021-1/desktop-followup-reference.png"><img src="../library-followup-ui-20261021-1/desktop-followup-reference.png" alt="电脑端原句追问后的实际书库依据"></a><a href="../library-followup-ui-20261021-1/phone-followup-reference-320.png"><img src="../library-followup-ui-20261021-1/phone-followup-reference-320.png" alt="320像素配对手机的实际原文依据"></a></div><p><a href="../library-followup-20261021/baseline.xml">问题复现</a> · <a href="../library-followup-20261021/final-regression.xml">最终回归</a> · <a href="../library-followup-ui-20261021-1/ui-report.json">两端操作记录</a></p></section>
<section><h2>怎样使用，以及仍存在什么不足</h2><ol><li>先从托盘彻底退出旧StudyForge，再打开上方“启动最新版源码”。已安装EXE没有自动更新。</li><li>在已保存的导师回答下点“针对这段追问”，选中具体原句，再问“这里为什么”。有已读相关书库内容时，可在本对话检索记录中核对实际原页。</li><li>直接点击生成讲解可沿用最后的原句追问；另填新的生成要求时按新要求检索。手机刷新后公共壳v64。</li></ol><p class="notice">剩余问题也保留：通用措辞仍可能命中无关背景章节；原文进入输入不保证模型正确使用、准确引用或解释到位。物理和统计回答仍有上述表述边界。本轮没有证明全软件内存、长视频速度或实体安卓触控已经通过，也没有重新打包。</p></section>
<script src="../../web/vendor/marked.js"></script><script src="../../web/vendor/purify.js"></script><script src="../../web/vendor/katex.js"></script><script src="../../web/lesson_render.js"></script><script type="application/json" id="data">__DATA__</script><script>
const examples=JSON.parse(document.getElementById('data').textContent),picker=document.getElementById('case'),view=document.getElementById('view');examples.forEach((item,index)=>{const option=document.createElement('option');option.value=index;option.textContent=item.title;picker.append(option);});
function show(){const item=examples[Number(picker.value)||0];document.getElementById('title').textContent=item.title;document.getElementById('question').textContent=item.question;document.getElementById('quote').textContent=item.quote;document.getElementById('original').textContent=item.original;document.getElementById('review').textContent=item.review;document.getElementById('control').textContent=item.same_request_body?'本组真实请求体完全相同：只作为重复采样对照，不归因为代码收益。':'本组书库参考发生改变：需要区分更好的原文输入与模型自身能力。';const host=document.getElementById('comparison');host.replaceChildren();for(const row of item.rows){const card=document.createElement('article');card.className='card '+(row.phase==='fixed'?'new':'old');const title=document.createElement('h3');title.textContent=row.phase==='fixed'?'修复后采样':'修复前采样';const label=document.createElement('p');label.className='badge';label.textContent=(row.original_reached_model?'已提供目标原文':'未提供目标原文')+' · '+row.seconds+'秒';const body=document.createElement(view.value==='context'?'pre':'div');body.className=view.value==='context'?'source':'lesson';body.dataset.raw=view.value==='context'?row.context:row.answer;if(view.value==='context')body.textContent=row.context||'（没有书库参考）';else renderLessonText(body,row.answer);const link=document.createElement('a');link.href='../library-followup-live-20261021-1/'+row.answer_file;link.textContent='打开原样最终回答';card.append(title,label,body,link);host.append(card);}}
picker.onchange=view.onchange=show;show();
</script></body></html>'''


if __name__=='__main__':main()
