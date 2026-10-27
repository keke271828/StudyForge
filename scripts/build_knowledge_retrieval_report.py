"""Offline before/after evidence, local ONNX results and real paired UI."""
from html import escape
import json
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/knowledge-retrieval-acceptance-20261021'
TITLE='知识库混合检索与条件保留验收'


def load(path): return json.loads(path.read_text(encoding='utf-8'))


def main():
    result=load(ROOT/'build/knowledge-retrieval-balance-20261021-4/report.json')
    model=load(ROOT/'build/knowledge-retrieval-real-20261021-2/report.json')
    comparison=load(ROOT/'build/knowledge-retrieval-real-comparison-20261021-1/report.json')
    real_book=load(ROOT/'build/knowledge-retrieval-real-book-20261021-1/report.json')
    ui=load(ROOT/'build/knowledge-retrieval-ui-20261021-2/ui-report.json')
    tests=ET.parse(ROOT/'build/knowledge-retrieval-20261021/final-regression.xml').getroot().findall('.//testcase')
    assert all(data['passed'] for data in (result,model,comparison,real_book,ui))
    assert tests and all(t.find(k) is None for t in tests for k in ('failure','error','skipped'))
    title_by_reading={hit['reading_id']:node['title'] for phase in result['candidates'] for node in phase['search_nodes'] for hit in node['semantic_hits']}
    candidates=[]
    for phase in result['candidates']:
        body='\n'.join(title_by_reading[h['reading_id']]+' · PDF '+str(h['page'])+' · 片段 '+str(h['ordinal']) for h in phase['hits'])
        candidates.append({'label':phase['phase'],'metric':str(phase['hit_count'])+'个片段 / '+str(phase['distinct_readings'])+'个小节',
            'text':body})
    examples=[{'title':'同一长页挤满候选','query':'改写后的同一问题（受控相似度）',
        'note':'一页有40个较高相似度片段，另一小节有一个相关位置。展示真实旧／新候选函数处理同一批受控向量的结果；不代表另一小节一定给出了正确答案。',
        'rows':candidates},
        {'title':'精确条件页被语义候选挤掉','query':'EXACT_DOMAIN_CONDITION',
        'note':'词面命中在第9页，定义在第8页，三个语义线索在第3、4、5页。下面为实际组装后送给导师的书库参考文本；没有模型润色。',
        'rows':[{'label':r['phase'],'metric':'PDF '+ '、'.join(map(str,r['pages'])),'text':r['result']['text']} for r in result['page_context']]},
        {'title':'同一页尾部的条件被裁掉','query':'EXACT_BOUNDARY_ASSUMPTION',
        'note':'语义位置在页首、精确条件在页尾。新摘录按真实词面命中选择连续窗口，没有词面命中时继续用有效语义位置。',
        'rows':[{'label':r['phase'],'metric':'原文字符 '+str(r['metadata']['start_char'])+'–'+str(r['metadata']['end_char']),
            'text':r['excerpt']} for r in result['same_page_excerpt']]}]
    before={q['query']:q['baseline']['expected_rank'] for q in comparison['queries']}
    rows=''.join('<tr><td>'+escape(q['query'])+'</td><td>'+escape(q['expected_title'])+'</td><td>'+str(q['keyword_expected_rank'] or '未命中')+
        '</td><td>'+str(before[q['query']] or '未命中')+'</td><td>'+str(q['hybrid_expected_rank'] or '未命中')+'</td></tr>' for q in model['queries'])
    books=''.join('<details><summary>'+escape(q['query'])+' · PDF '+ '、'.join(str(e['page']) for e in q['context']['evidence'])+
        '</summary><pre>'+escape(q['context']['text'])+'</pre></details>' for q in real_book['queries'])
    checks=''.join('<li>'+escape(item)+'</li>' for item in ui['checks'])
    pool=result['candidate_buffer']
    payload=json.dumps(examples,ensure_ascii=False).replace('<','\\u003c')
    html=TEMPLATE
    for key,value in {'COUNT':str(len(tests)),'UI_COUNT':str(len(ui['checks'])),'MODEL_ROWS':rows,'BOOKS':books,
        'CHECKS':checks,'PAYLOAD':payload,'POOL_SECONDS':f"{pool['seconds']:.3f}",'POOL_BYTES':f"{pool['python_peak_bytes']:,}"}.items():
        html=html.replace('__'+key+'__',value)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/(TITLE+'.html')).write_text(html,encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({'python_checks':len(tests),'node_checks':3,'ui_checks':len(ui['checks']),
        'controlled_before_after_examples':3,'real_local_embedding_queries':5,'real_scanned_book_queries':3,
        'cloud_generation_requests':0,'new_unread_ocr_pages':0,'fresh_index_required':False,
        'packaged':False,'helper_peak_python_bytes':pool['python_peak_bytes']},ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUT/(TITLE+'.html'))


TEMPLATE=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>知识库混合检索与条件保留验收</title>
<style>:root{font:16px/1.85 system-ui,"Microsoft YaHei",sans-serif;color:#254335;background:#edf2e9}*{box-sizing:border-box}body{max-width:1200px;margin:auto;padding:28px 18px}header,section,.card{background:#fffefa;border:1px solid #ccd9cc;border-radius:18px;padding:24px;margin:18px 0;min-width:0}h1{font-size:31px;line-height:1.4}h2{font-size:23px}h3{font-size:18px}a{color:#14674d;overflow-wrap:anywhere}.note{padding:13px 16px;background:#fff3db;border-left:4px solid #b48b48}.muted{font-size:13px;color:#536958}.flow{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.flow div{background:#e9f2e6;padding:13px;border-radius:12px;text-align:center}.flow strong{display:block}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center}select,button{font:inherit;padding:9px 12px;border:1px solid #aac3ae;border-radius:9px;background:#f5f8f0;color:#244434;max-width:100%;cursor:pointer}select:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #49977d;outline-offset:3px}.compare{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px}.card{padding:17px;margin:0}.before{border-top:4px solid #b79761}.after{border-top:4px solid #42816a}.badge{font-size:13px;padding:4px 9px;border-radius:18px;background:#e3eee0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.85 Consolas,"Microsoft YaHei",monospace;background:#eef4ea;border:1px solid #dae3d5;padding:14px;border-radius:10px;max-height:540px;overflow:auto}mark{background:#fae4a4;color:#473b22}summary{cursor:pointer;font-weight:650}details{margin:14px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:600px}td,th{text-align:left;vertical-align:top;border:1px solid #cedccc;padding:10px}img{max-width:100%;height:auto;border:1px solid #ccd9cc;border-radius:12px}.shots{display:grid;grid-template-columns:2fr 1fr;gap:16px;align-items:start}.shots>a{min-width:0}li{margin:7px 0}.metric{font-size:22px;font-weight:650}@media(max-width:820px){.compare,.shots{grid-template-columns:1fr}.flow{grid-template-columns:1fr}.flow div{text-align:left}body{padding:12px}header,section{padding:16px}h1{font-size:25px}}</style></head><body>
<header><span class="badge">STUDYFORGE · 2026-10-21 · 源码未打包</span><h1>知识库：找得到，还要保住条件</h1><p>这轮完善已经存在的混合检索：让不同章节有机会进入候选，保留精确术语与适用条件，并保留连续的原文位置。已有有效阅读和索引可以继续使用。</p><p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../web/help/guide.html#library">软件内指南</a> · <a href="../../docs/知识库混合检索与条件保留验收.md">完整方法、验证与限制</a></p><div class="note">以下包含3组真实本机函数对照、真实本地ONNX检索、此前已读扫描教材的原文回查及完整界面操作。<strong>没有新增云端教学回答评测，也没有重新通读未选章节。</strong>检索命中不等于知识正确、AI理解无误或学生已经掌握。</div></header>
<section><h2>这条链路现在怎样工作</h2><div class="flow"><div><strong>① 已授权已读范围</strong>先检查当前阅读版本</div><div><strong>② 两类候选</strong>关键词＋本地语义</div><div><strong>③ 分组与融合</strong>同页去重、兼顾章节</div><div><strong>④ 有界原文摘录</strong>精确条件＋邻页上下文</div><div><strong>⑤ 导师／成果</strong>保留来源与疑点</div></div><p>节点级原本已有排名融合，本轮把互补原则落实到页级，并修复页内语义位置覆盖精确词面位置的问题。未换默认模型、未增加固定审核／重排轮次、未要求重建全书索引。</p><p class="muted">参考：<a href="https://www.anthropic.com/research/contextual-retrieval">Anthropic：结合词面、语义与上下文</a>；<a href="https://qdrant.tech/documentation/search/hybrid-queries/">Qdrant：按排名融合不同检索结果</a>。公开实验的收益不代表本软件的实测收益。</p></section>
<section><h2>切换三个实际旧／新对照</h2><div class="controls"><label for="example">问题场景</label><select id="example"></select></div><h3 id="caseTitle"></h3><p id="caseNote"></p><p>查询：<code id="caseQuery"></code></p><div class="compare" id="comparison"></div><p class="muted">原始输出保留，不用AI润色成更漂亮的结果。对照中固定相似度的部分是受控复现；它验证算法行为，不是本地模型准确率测试。</p><p><a href="../knowledge-retrieval-balance-20261021-4/report.json">完整对照数据</a> · <a href="../knowledge-retrieval-20261021/baseline-functions/manifest.json">修复前函数指纹</a> · <a href="../knowledge-retrieval-20261021/baseline-tests.xml">最初8项问题复现</a> · <a href="../knowledge-retrieval-20261021/anchor-baseline-tests.xml">同页页尾问题复现</a></p></section>
<section><h2>真实本地模型：五个跨领域改写查询</h2><p>实际运行固定版本的多语言E5小模型。5个目标全部进入前三，其中4个第一、1个第二；同一保存语料上的旧／新混合排名一致，新结果减少了同页重复位置，没有宣称这五题排名提升。这些是合成的保存文本，不是五本教材的真实通读；排名只判断预先指定的目标是否找到。</p><div class="scroll"><table><thead><tr><th>实际问题</th><th>目标内容</th><th>关键词排名</th><th>旧混合排名</th><th>新混合排名</th></tr></thead><tbody>__MODEL_ROWS__</tbody></table></div><p><a href="../knowledge-retrieval-real-20261021-2/report.json">完整本地模型查询与摘录</a> · <a href="../knowledge-retrieval-real-comparison-20261021-1/report.json">同一语料旧／新真实模型对照</a></p></section>
<section><h2>复用真实扫描教材的已读内容</h2><p>沿用此前已授权的《高等代数》“数域”阅读记录，在独立副本中检索。三个问题均只返回PDF第6、7页，没有新OCR、云端调用或读取其他未选正文。原页文字、AI图像记录和导航笔记继续分开标明。</p>__BOOKS__<p><a href="../knowledge-retrieval-real-book-20261021-1/report.json">真实教材回查与模型内存记录</a></p><div class="note">本地模型仍有内存成本：该独立进程加载后约446MiB，关闭释放后约81.6MiB。本轮控制的是检索候选缓冲，不能据此声称整个应用的高内存问题已解决。</div></section>
<section><h2>速度与缓冲边界</h2><p class="metric">12万个合成片段 · __POOL_SECONDS__秒</p><p>默认24个候选，10,000个组，最多保留24个完成组与1个当前组，每组最多3个原页位置；候选缓冲总位置边界75。额外追踪的Python分配峰值为__POOL_BYTES__字节。</p><p class="muted">这只测纯候选缓冲，计时和分配追踪分开，追踪前清空Python自由列表。不含数据库矩阵、ONNX、分词器、OCR、云端或整个应用RSS；不是完整任务提速比例。已有模型、阈值、有效索引仍保留。</p></section>
<section><h2>相关功能与两端操作</h2><p><strong>__COUNT__项Python相关回归通过；3项共享核查组件Node检查通过。最终源码的__UI_COUNT__项实际Electron／配对HTTPS手机操作通过，控制台错误0项。</strong></p><p>新增原生请求验证：导师和DOCX生成确实收到“除数必须非零”的原文与相邻定义，手动范围外章节没有混入，也没有同步习题。云端传输使用受控回复，不能算真实模型教学质量证明。手机是320像素窗口配对测试，尚非实体安卓触控验收。</p><details><summary>展开全部__UI_COUNT__项界面检查</summary><ul>__CHECKS__</ul></details><p><a href="../knowledge-retrieval-20261021/final-regression.xml">最终回归记录</a> · <a href="../knowledge-retrieval-ui-20261021-2/ui-report.json">完整两端操作记录</a></p><div class="shots"><a href="../knowledge-retrieval-ui-20261021-2/desktop-book-semantic.png"><img src="../knowledge-retrieval-ui-20261021-2/desktop-book-semantic.png" alt="电脑书库实际语义检索与目录"></a><a href="../knowledge-retrieval-ui-20261021-2/phone-book-library-320.png"><img src="../knowledge-retrieval-ui-20261021-2/phone-book-library-320.png" alt="配对手机书库"></a></div></section>
<section><h2>下次打开这样验收</h2><ol><li>在系统托盘彻底退出旧StudyForge，然后打开上方“启动最新版源码”。已安装EXE未被本轮源码自动替换。</li><li>全局书库→智能检索→“关键词＋本地语义”。内存紧张时可保留仅关键词；已有有效阅读和索引继续使用。</li><li>搜索概念或改写问题，定位到节点后，按当前对话的自动参考／手动引用使用。未读范围仍需你主动安排。</li><li>在导师或成果的资料依据中核对原页、摘录范围和疑点。重要推导仍应回查原文条件，不把候选分数当作正确性认证。</li></ol><p>手机连接同一最新版后刷新，公共壳v62；两端共享检索索引，聊天与引用选择保持原有隔离。</p></section>
<script type="application/json" id="examples">__PAYLOAD__</script><script>
const examples=JSON.parse(document.getElementById('examples').textContent),select=document.getElementById('example');
examples.forEach((item,i)=>{const option=document.createElement('option');option.value=i;option.textContent=item.title;select.append(option);});
function show(){const item=examples[Number(select.value)||0];document.getElementById('caseTitle').textContent=item.title;document.getElementById('caseQuery').textContent=item.query;document.getElementById('caseNote').textContent=item.note;const root=document.getElementById('comparison');root.replaceChildren();for(const row of item.rows){const card=document.createElement('article');card.className='card '+(row.label==='fixed'?'after':'before');const title=document.createElement('h3');title.textContent=row.label==='fixed'?'修复后':'旧实现';const metric=document.createElement('p');metric.className='badge';metric.textContent=row.metric;const pre=document.createElement('pre');pre.className='exact-output';pre.textContent=row.text;card.append(title,metric,pre);root.append(card);}}
select.onchange=show;show();
</script></body></html>'''


if __name__=='__main__': main()
