"""Evidence-gated chapter scheduling report with actual controlled timelines."""
import hashlib
import html
import json
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

from docx import Document

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/chapter-continuity-final-20261026'
UI=ROOT/'build/chapter-continuity-ui-20261026-4'
OUT=ROOT/'build/chapter-continuity-acceptance-20261026'


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def link(path,label):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(label)+'</a>'


def main():
    gate,ui,flow=load(GATE/'command.json'),load(UI/'ui-report.json'),load(UI/'flow.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert gate['production_after']=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in gate['production_after']}
    tests=ET.parse(GATE/'regression.xml').getroot().findall('.//testcase')
    targeted=[test for test in tests if test.get('classname')=='tests.test_chapter_continuity']
    assert len(targeted)==27 and len(flow['jobs'])==3 and flow['calls']==15
    assert flow['mastery']==flow['learning_events']==0
    for filename,count in [('chapter-continuity-before-20261026.xml',4),('chapter-context-empty-before-20261026.xml',1)]:
        cases=ET.parse(ROOT/'build'/filename).getroot().findall('.//testcase')
        assert sum(case.find('failure') is not None for case in cases)==count
    items=[]
    for index,job in enumerate(flow['jobs']):
        key=('dependent','independent','serial')[index]
        artifact=job['artifact'];word=UI/(key+'.docx')
        assert job['status']=='completed' and hashlib.sha256(word.read_bytes()).hexdigest()==artifact['sha256']
        with zipfile.ZipFile(word) as archive:
            assert archive.testzip() is None and b'<m:oMath' in archive.read('word/document.xml')
        text='\n'.join(p.text for p in Document(word).paragraphs)
        assert all(value in text for value in ('DRAFT_PART_1','DRAFT_PART_2','系统性总结'))
        assert all(row['content_origin']['role']=='ai_generated_artifact' for row in artifact['metadata']['source_reading'])
        events=[event for event in flow['events'] if event['job_id']==job['id']]
        def event(role,part,phase):return next(row for row in events if row['role']==role and row['part']==part and row['phase']==phase)
        second,first_end=event('draft',2,'start'),event('review',1,'end')
        if key=='independent':
            assert events.index(second)<events.index(event('draft',1,'end')) and not second['previous']
        else:
            assert events.index(second)>events.index(first_end) and second['previous']
        origin=min(row['at'] for row in events);end=max(row['at'] for row in events)
        spans=[]
        for role,part in [('draft',1),('review',1),('draft',2),('review',2),('summary',0)]:
            spans.append({'role':role,'part':part,'start':event(role,part,'start')['at']-origin,
                          'end':event(role,part,'end')['at']-origin})
        items.append({'key':key,'title':('续接内容 · 内部并行开启','独立内容 · 内部并行开启','独立内容 · 内部并行关闭')[index],
            'plan':job['plan'],'parallel':job['parallel'],'spans':spans,'duration':end-origin,
            'previous_supplied':second['previous'],'word_sha256':artifact['sha256'],'word':word.as_uri()})
    OUT.mkdir(exist_ok=True)
    receipt={'passed':True,'regression':gate['tests'],'targeted_checks':len(targeted),'native_checks':len(ui['checks']),
        'production_sha256':gate['production_after'],'reproduced_failures':5,'controlled_model_requests':15,
        'external_model_requests':0,'word_downloads':3,'real_user_data_used':False,'packaged':False,
        'physical_android':False,'model_quality_verified':False,'whole_app_performance_verified':False}
    (OUT/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>章节续接与实际并行验收</title><style>*{box-sizing:border-box}body{max-width:1120px;margin:36px auto;padding:0 24px 60px;background:#f0f4ec;color:#223e32;font:16px/1.9 system-ui,"Microsoft YaHei",sans-serif}header,section{padding:27px 32px;margin:22px 0;border:1px solid #d8e1d4;border-radius:18px;background:#fffefa}h1{font-size:31px;line-height:1.45}h2{font-size:23px}a{color:#28684e}.muted,figcaption,.eyebrow{color:#546c5d;font-size:13px}.notice{background:#e8f0e4;padding:16px 20px;border-radius:11px}button{font:inherit;padding:8px 13px;margin:4px;border-radius:9px;border:1px solid #abc1ab;background:#f4f7ef;color:#254f3b;cursor:pointer}button[aria-pressed="true"]{background:#2c6b50;color:white}.timeline{margin:26px 0}.lane{display:grid;grid-template-columns:138px 1fr;align-items:center;gap:15px;margin:13px 0}.track{height:32px;position:relative;background:repeating-linear-gradient(to right,#edf2e9 0,#edf2e9 calc(25% - 1px),#d7e2d3 25%);border-radius:8px}.bar{position:absolute;height:24px;top:4px;border-radius:5px;min-width:2px;background:#3e8566}.bar.review{background:#bd8a3b}.bar.summary{background:#587da2}.legend span{display:inline-block;padding:4px 11px;border-radius:7px;margin-right:10px;color:white;background:#3e8566;font-size:13px}.legend .review{background:#bd8a3b}.legend .summary{background:#587da2}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3e9;padding:16px;border-radius:10px;font-size:13px}img{max-width:100%;border:1px solid #d2dfcd;border-radius:12px}.phone img{max-width:320px}figure{margin:20px 0}li{margin:8px 0}summary{cursor:pointer;font-weight:600;padding:10px 0}@media(max-width:700px){body{padding:0 12px}header,section{padding:20px}.lane{grid-template-columns:105px 1fr;gap:8px;font-size:13px}h1{font-size:26px}}</style>
<header><div class="eyebrow">2026-10-26 · 生成讲解文档 · 源码验收</div><h1>续接的推导等前文，独立章节真正并行</h1><p>引用已有AI成果再生成讲解时，资料身份信息不能挡住正文的续接标记；文件名也不能决定两章是否有关。</p><p class="notice">本轮验证生成顺序、实际输入与Word交付。AI返回为受控夹具，不能据此认证真实教学质量或实际模型速度。</p></header>
<section><h2>修复了什么</h2><ul><li>识别完整、版本一致的资料身份封装，在正文中判断续接；身份信息仍完整交给模型，不把AI成果变成教材事实。</li><li>正文开头的“原文续接”、接续证明／推导决定等待；文件名、代码块、引用及后文提及这些词不自动制造依赖。</li><li>没有已完成草稿时不再发送空的“已写内容衔接”标题。真正的续接部分等待前一部分完成所选核查后，才接收其草稿。</li><li>失败任务重试时，可以复用的第一部分继续复用；缺少前文的旧第二部分因输入变化重新生成，不照搬旧缓存。</li></ul></section>
<section><h2>开关实际改变了执行顺序</h2><p>以下来自真实桌面按钮启动的三项隔离任务。点击切换，查看受控模型请求进入及返回的实际记录；每项包含两部分撰写、两次快速核查和一次整体总结。</p><div id="choices"></div><h3 id="caseTitle"></h3><div class="legend"><span>撰写</span><span class="review">核查</span><span class="summary">整体总结</span></div><div id="timeline" class="timeline"></div><p id="outcome" class="notice"></p><p class="muted">条形宽度来自测试夹具的模拟等待，只显示是否重叠及依赖先后，不是模型耗时、token速度或全软件性能基准。独立并行测试通过事件同步确认两请求可同时进入，不依赖短延时和Windows时钟精度。</p><details><summary>查看本任务保存的依赖计划</summary><pre id="plan"></pre></details><p id="download"></p></section>'''
    page+='<section><h2>最终验证</h2><ul><li>'+str(gate['tests']['total'])+'项关联测试通过，0失败、0错误、0跳过；4个生产文件指纹一致。</li><li>27项专门检查：有效／未知封装、实际分段、真实正文与文件名、空衔接、开关差异、完整Word，以及旧草稿缓存恢复。</li><li>7组实际电脑／配对HTTPS手机检查通过：三项生成、并行开关、公式显示、三个Word下载与哈希、390／320px和刷新恢复。</li><li>15次受控模型请求，0次外部模型请求；没有真实用户数据、掌握度或学习事件写入。核查夹具的通过标记不认证数学或教学内容。</li></ul><p>修复前4项依赖检查失败，另复现1项空衔接输入失败。验收过程中，两次夹具把预期两个独立来源分成四段，已按清单及身份信息长度动态安排测试预算；另将短模拟延迟改为事件同步。首轮实际UI还暴露出空衔接标题问题，修复后重新完成最终检查。旧日志和失败截图保留，未计作最终通过。</p><p class="notice">本轮没有增加固定AI核查轮数，没有重写已交付文档；首部分命中缓存可继续复用，但上下文改变的未完成续写可能需要重新请求。仍不能保证所有概念依赖都被自动识别，隐含前置关系、证明正确性和整体教学质量需继续核验。</p></section>'
    page+='<section><h2>实际界面与手机阅读</h2><figure><img alt="桌面实际完成的续接讲解" src="'+(UI/'desktop-dependent-chapters.png').as_uri()+'"><figcaption>受控任务从桌面生成入口启动；导出的完整讲解出现在原对话和成果快选中。</figcaption></figure><figure class="phone"><img alt="配对手机320像素阅读" src="'+(UI/'phone-chapters-320.png').as_uri()+'"><figcaption>配对HTTPS手机实际阅读与公式显示。未在实体安卓重复验收；画面中的内容为流程夹具。</figcaption></figure></section>'
    page+='<section><h2>打开最新版</h2><p>先从Windows托盘完全退出旧版，再双击 '+link(ROOT/'验收最新版.vbs','验收最新版.vbs')+'。在讲解选项里切换“任务内部并行”。本轮未重新打包，旧安装包不包含此源码修改。</p><p>'+link(OUT/'result.json','验收索引')+' · '+link(GATE/'command.json','最终回归与源码指纹')+' · '+link(UI/'ui-report.json','两端操作记录')+' · '+link(UI/'flow.json','实际模型步骤与任务元数据')+'</p></section>'
    page+='<script id="caseData" type="application/json">'+json.dumps(items,ensure_ascii=False).replace('<','\\u003c')+'</script>'
    page+='''<script>const cases=JSON.parse(document.getElementById('caseData').textContent),byId=id=>document.getElementById(id);function show(index){const item=cases[index];byId('caseTitle').textContent=item.title;byId('timeline').replaceChildren();for(const span of item.spans){const lane=document.createElement('div'),label=document.createElement('span'),track=document.createElement('div'),bar=document.createElement('div');lane.className='lane';label.textContent=span.role==='summary'?'整体总结':(span.role==='draft'?'撰写':'核查')+'第'+span.part+'部分';track.className='track';bar.className='bar '+span.role;bar.style.left=(span.start/item.duration*100)+'%';bar.style.width=((span.end-span.start)/item.duration*100)+'%';bar.title=label.textContent+'：相对进入 '+span.start.toFixed(3)+'，返回 '+span.end.toFixed(3);track.append(bar);lane.append(label,track);byId('timeline').append(lane);}byId('outcome').textContent=item.key==='dependent'?'内部并行已开启，但第2部分仍在第1部分核查完成后开始，并获得已完成草稿。':item.key==='independent'?'两部分撰写请求实际重叠；第2部分没有收到不存在的前章草稿。':'同一套独立资料关闭内部并行后，第2部分等待第1部分核查完成再开始。';byId('plan').textContent=JSON.stringify(item.plan,null,2);const a=document.createElement('a');a.href=item.word;a.textContent='打开本任务完整Word（受控验收示例）';byId('download').replaceChildren(a);document.querySelectorAll('[data-case]').forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));}for(const [i,item]of cases.entries()){const button=document.createElement('button');button.type='button';button.dataset.case=i;button.textContent=item.title;button.onclick=()=>show(i);byId('choices').append(button);}show(0);</script></html>'''
    target=OUT/'章节续接与实际并行验收.html';target.write_text(page,encoding='utf-8');print(target)


if __name__=='__main__':main()
