"""Evidence-gated, readable real-answer comparison for long source focus."""
import hashlib
import html
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.source_focus_cases import CASES

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/source-focus-final-20261026-2'
UI=ROOT/'build/source-focus-ui-20261026-2'
LIVE=ROOT/'build/source-focus-live-20261026'
ALLOCATION=ROOT/'build/source-focus-allocation-20261026-2'
OUT=ROOT/'build/source-focus-acceptance-20261026'


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def link(path,label):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(label)+'</a>'


def main():
    gate,ui,live,recheck=load(GATE/'command.json'),load(UI/'ui-report.json'),load(LIVE/'report.json'),load(LIVE/'final-input-recheck.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed'] and recheck['passed']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert gate['production_after']=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in gate['production_after']}
    testcases=ET.parse(GATE/'regression.xml').getroot().findall('.//testcase')
    targeted=[row for row in testcases if row.get('classname') in ('tests.test_source_focus','tests.test_chat_source_focus')]
    assert len(live['results'])==4 and all(row['status']=='completed' and row['request_count']==1 for row in live['results'])
    payload=[]
    for case,material in CASES.items():
        comparison={'case':case,'title':material['title'],'question':material['question'],'tail':material['tail'],'arms':{}}
        for arm in ('legacy','focused'):
            row=next(x for x in live['results'] if x['case']==case and x['arm']==arm)
            text=(LIVE/row['answer_file']).read_text(encoding='utf-8')
            assert hashlib.sha256(text.encode()).hexdigest()==row['answer_sha256']
            requests=load(LIVE/(case+'-'+arm+'-requests.json'))
            comparison['arms'][arm]={'text':text,'seconds':row['seconds'],'first':row['first_visible_seconds'],
                'prompt_tokens':requests[0]['usage']['prompt_tokens'],'completion_tokens':requests[0]['usage']['completion_tokens'],
                'reasoning_tokens':requests[0]['usage'].get('completion_tokens_details',{}).get('reasoning_tokens'),
                'cached_tokens':requests[0]['usage'].get('prompt_cache_hit_tokens'),
                'source_characters':row['input_receipt']['context_characters'],
                'targets':row['input_receipt']['targets_supplied'],'response_models':requests[0]['response_models']}
            assert (all(comparison['arms'][arm]['targets'].values())) is (arm=='focused')
        payload.append(comparison)
    OUT.mkdir(exist_ok=True)
    receipt={'passed':True,'regression':gate['tests'],'targeted_checks':len(targeted),'native_checks':len(ui['checks']),
             'source_sha256':gate['production_after'],'controlled_model_requests':2,'real_model_requests':4,
             'synthetic_material':True,'synthetic_reading_record':True,'private_reasoning_saved':False,
             'final_live_inputs_rechecked':True,'packaged':False,'physical_android':False,'whole_app_ram_verified':False,
             'receipts':{'gate':str(GATE/'command.json'),'ui':str(UI/'ui-report.json'),'live':str(LIVE/'report.json'),
                         'final_inputs':str(LIVE/'final-input-recheck.json'),'allocation':str(ALLOCATION/'result.json')}}
    (OUT/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    assets=''.join('<script src="'+(ROOT/'web'/name).as_uri()+'"></script>' for name in
                   ('vendor/marked.js','vendor/purify.js','vendor/katex.js','lesson_render.js'))
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>长资料定位与导师讲解实际对照</title>
<style>*{box-sizing:border-box}body{max-width:1260px;margin:32px auto;padding:0 24px 70px;background:#f1f4ed;color:#203d32;font:16px/1.85 system-ui,"Microsoft YaHei",sans-serif}header,section{background:#fffefa;border:1px solid #d8e1d5;border-radius:18px;padding:28px 32px;margin:22px 0}h1{font-size:32px;line-height:1.4}h2{font-size:23px}h3{font-size:18px}.eyebrow,figcaption,.muted{color:#536c5e;font-size:13px}.notice{padding:15px 20px;background:#e8f0e5;border-radius:12px}a{color:#276b50}button{font:inherit;background:#f3f7ef;color:#214b39;border:1px solid #a7c1ab;border-radius:9px;padding:9px 16px;cursor:pointer;margin:4px}button[aria-pressed="true"]{background:#28674e;color:white}.columns{display:grid;grid-template-columns:1fr 1fr;gap:22px}.answer{border:1px solid #d4e0d2;border-radius:13px;padding:20px;min-width:0}.answer.new{border-color:#43886b;background:#fcfff9}.answer h3{margin-top:0}table{border-collapse:collapse;width:100%;margin:20px 0;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #d9e3d6;text-align:left}.table-wrap{overflow:auto}.question,pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef4e9;border-radius:10px;padding:16px}blockquote{border-left:3px solid #7e9e86;padding-left:16px;color:#475c53}.lesson-explanation{overflow-wrap:anywhere}.katex-display{overflow:auto;max-width:100%;padding:4px}img{max-width:100%;border-radius:12px;border:1px solid #d4e0d2}.phone img{max-width:320px}summary{cursor:pointer;padding:10px 0;font-weight:600}figure{margin:20px 0}.raw-links{font-size:13px}li{margin:8px 0}@media(max-width:800px){body{padding:0 12px}header,section{padding:20px}.columns{grid-template-columns:1fr}h1{font-size:26px}}</style>'''
    page+='<link rel="stylesheet" href="'+(ROOT/'web/vendor/katex.css').as_uri()+'">'
    page+='''<header><div class="eyebrow">2026-10-26 · 学习质量与输入效率 · 真实模型原样回答</div><h1>先把相关原文交给导师</h1><p>长资料不再固定截取开头。导师按当前问题收到相关原文、相邻定义与条件；旧笔记继续只作导航。</p><p class="notice">这轮改的是输入选择。没有增加固定AI审查轮次，没有用更多人格提示替代缺失原文；生成讲解文档仍使用完整所选范围。</p></header>
<section><h2>为什么原先讲不透</h2><p>超过6万字符的所选资料，原路径只发送阅读笔记加原文开头约4.5万字符。即使当前问题指向末尾，导师也可能收不到原定义和例子。已在DeepSeek与Codex两条真实对话入口用受控服务复现。</p><p>新版在本次获准、已完成准备的内容中进行本地词面定位。原文片段附来源和可核对坐标，保留相邻内容；不从公式或代码围栏中间切开，跨页未闭合时继续寻找边界。完整相关块放不下或没有明确命中时不猜补原文。</p><p>手机请求没有附通读ID时，现在可恢复<strong>当前对话</strong>保存的阅读记录，仍核对所选文件及内容版本；不会自动拿其他项目或对话的记录顶替。明确部分解析与未读文件的限制保留。</p></section>
<section><h2>同模型：看完整回答再判断</h2><p>DeepSeek Flash / high、精学、直观与专业并存。两份人工长资料，每个方案各请求一次；代数先旧后新，社会科学先新后旧。两组教学规则和问题相同，只替换本地原文选择。预备阅读记录为人工测试夹具，不是整本真实通读速度测试。</p><div id="caseButtons"></div><h3 id="caseTitle"></h3><div id="question" class="question"></div><details><summary>查看放在资料末尾的原文（人工样本）</summary><pre id="sourceTail"></pre></details><div class="table-wrap"><table><thead><tr><th>指标</th><th>旧：固定原文开头</th><th>新：相关原文与相邻内容</th></tr></thead><tbody id="metrics"></tbody></table></div><p class="muted">输入token为服务端usage；包含教学规则，不仅是原文。缓存命中和模型生成长度不同，耗时只能说明这两组抽样，不能承诺所有任务同比提速。</p><div class="columns"><article class="answer"><h3>旧路径 · 原样回答</h3><div id="oldAnswer"></div></article><article class="answer new"><h3>新版 · 原样回答</h3><div id="newAnswer"></div></article></div><p id="assessment" class="notice"></p></section>
<section><h2>我的判断与剩余不足</h2><p>这两例新版更适合当前学习任务：代数直接解释陪集乘积与uv−1∈I的等价关系，再完成模6的两个原例；社会科学完成材料中81.2、72.8和8.4的计算，直接说明构成差异及因果识别边界。</p><p>旧版虽然坦诚说明后半原文缺失，但代数仍转用训练知识补例，社会科学引入额外分解公式和另造数据，偏离“只按材料”的要求。新版减少了这种绕路；这不是证明它解决了全部教学问题。</p><p>仍有改进空间：新版没有逐段标注来源位置；社会科学开头把“观察差”与“效果”并列得较绝对，更准确的说法是“不能据此认定因果效应”，后文保留了层内差为零也不证明真实效应为零的限制。本轮没有把这些个例再堆进通用提示词。</p><p>当前定位属于词面导航。换一种说法、纯符号追问或远距离前置关系仍可能漏检；没有命中时需要更明确的概念、原句引用或页码，检索命中也不认证理解完整。</p></section>'''
    page+='<section><h2>最终验证</h2><ul><li>'+str(gate['tests']['total'])+'项关联回归通过，0失败、0错误、0跳过；5个生产文件指纹一致。</li><li>'+str(len(targeted))+'项专门检查：两服务入口、手机式省略通读ID、引用原句、短资料全文、过期／跨项目记录、公式／代码跨页、无命中、原文坐标及来源身份。</li><li>6组实际电脑／配对HTTPS手机操作，2次受控模型请求；切换项目和刷新不重复调用，390／320px公式正常。合成内容不写入真实学习画像。</li><li>4次真实模型请求均保存完整最终回答和非敏感请求；最终定位器重新准备的两个新版输入与真实请求逐字一致，复核没有新云调用。</li></ul><p>局部资源探测使用每份2,174,327字符人工资料：单任务与双任务分别测Python分配峰值和耗时，结果仅描述本定位函数，不含已有输入分配，不代表整个软件RAM、OCR、视频或生成速度已解决。</p><p class="muted">验收过程也保留：首轮复现夹具未超过6万字符门槛，不作缺陷证据；修正后两入口均复现。首轮完整回归351通过、4失败，暴露出既有测试以1000字符硬切时受绝对路径长度影响；调整夹具预算保持预期两段，实际通读分段逻辑没有修改。修订夹具时一次缺少re导入的4项错误已纠正，后续67项聚焦测试及本次完整回归均重新执行。</p></section>'
    page+='<section><h2>实际界面</h2><figure><img alt="电脑端实际受控回复" src="'+(UI/'desktop-source-focus.png').as_uri()+'"><figcaption>电脑端实际发送、相关原文进入请求，公式正常显示。界面回复为受控夹具，真实模型回答在上面对照区。</figcaption></figure><figure class="phone"><img alt="320像素手机端实际受控回复" src="'+(UI/'phone-source-focus-320.png').as_uri()+'"><figcaption>配对HTTPS手机界面，未在实体安卓设备重复验收。</figcaption></figure></section>'
    page+='<section><h2>打开最新版与原始凭据</h2><p>先从Windows托盘完全退出旧版，再双击 '+link(ROOT/'验收最新版.vbs','验收最新版.vbs')+'。本轮为源码更新，没有重新打包，旧0.4.4安装包不包含此轮修改。</p><p class="raw-links">'+link(OUT/'result.json','验收索引')+' · '+link(GATE/'command.json','最终回归与源码指纹')+' · '+link(UI/'ui-report.json','两端操作')+' · '+link(LIVE/'report.json','真实调用指标')+' · '+link(LIVE/'final-input-recheck.json','最终输入逐字复核')+' · '+link(ALLOCATION/'result.json','局部资源探测')+'</p><p class="raw-links">'
    page+=' · '.join(link(LIVE/(case+'-'+arm+'.md'),('代数' if case=='algebra' else '社会科学')+'／'+('旧' if arm=='legacy' else '新')+'完整原回答') for case in CASES for arm in ('legacy','focused'))
    page+='</p></section>'+assets
    page+='<script id="comparisonData" type="application/json">'+json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')+'</script>'
    page+='''<script>const data=JSON.parse(document.getElementById('comparisonData').textContent),byId=id=>document.getElementById(id);function show(index){const row=data[index],old=row.arms.legacy,fresh=row.arms.focused;byId('caseTitle').textContent=row.title;byId('question').textContent=row.question;byId('sourceTail').textContent=row.tail;renderLessonText(byId('oldAnswer'),old.text);renderLessonText(byId('newAnswer'),fresh.text);byId('metrics').replaceChildren();for(const [label,key]of [['原文相关上下文字符','source_characters'],['整个请求输入token','prompt_tokens'],['输出token（含推理）','completion_tokens'],['其中推理token数（不保存内容）','reasoning_tokens'],['输入缓存命中token','cached_tokens'],['首段可见秒数','first'],['整次完成秒数','seconds']]){const tr=document.createElement('tr');for(const value of [label,old[key]??'未返回',fresh[key]??'未返回']){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}byId('metrics').append(tr);}byId('assessment').textContent=index===0?'新版拿到了原定义和两个例子，解释“uv−1∈I”的含义，并区分非零与存在逆元；旧版缺原文，只能另作标准背景补充。':'新版直接用材料的分层数据完成均分计算；旧版没有收到数据，另引分解公式和自拟例子。对当前“只按材料”的要求，新版更贴近。';document.querySelectorAll('[data-case]').forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));}for(const [i,row]of data.entries()){const button=document.createElement('button');button.type='button';button.dataset.case=i;button.textContent=row.title;button.onclick=()=>show(i);byId('caseButtons').append(button);}show(0);</script></html>'''
    target=OUT/'长资料定位与导师讲解实际对照.html';target.write_text(page,encoding='utf-8');print(target)


if __name__=='__main__':main()
