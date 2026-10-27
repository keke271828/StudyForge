import hashlib,html,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/knowledge-continuity-final-20261026'
UI=ROOT/'build/knowledge-continuity-ui-20261026-1'
OUT=ROOT/'build/knowledge-continuity-acceptance-20261026'

def main():
    gate=json.loads((GATE/'command.json').read_text(encoding='utf-8'))
    ui=json.loads((UI/'ui-report.json').read_text(encoding='utf-8'))
    assert gate['exit_code']==0 and gate['source_frozen'] and not any(gate['tests'][k] for k in ('failure','error','skipped'))
    for name,digest in gate['production_after'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    assert ui['passed'] and ui['external_model_requests']==0 and not ui['console_errors']
    node=(GATE/'node-tests.log').read_text(encoding='utf-8-sig')
    assert re.search(r'# fail 0\b',node) and re.search(r'# skipped 0\b',node)
    count=int(re.search(r'# tests (\d+)',node)[1]);OUT.mkdir(exist_ok=True)
    (OUT/'verification.json').write_text(json.dumps({'python':gate,'node_tests':count,'native':ui,
        'packaged':False,'learning_quality_benchmark':False},ensure_ascii=False,indent=2),encoding='utf-8')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>知识结构接续与公式阅读验收</title><style>
    *{box-sizing:border-box}body{font:16px/1.85 system-ui,"Microsoft YaHei",sans-serif;background:#f2f4ee;color:#203e32;margin:0}main{max-width:1100px;margin:auto;padding:36px 24px}header,section{border:1px solid #d9e4d9;background:#fffef9;border-radius:20px;padding:26px;margin-bottom:20px}h1{font-size:32px;line-height:1.3}h2{font-size:23px}a{color:#17654f}table{border-collapse:collapse;width:100%}th,td{text-align:left;vertical-align:top;padding:14px;border-bottom:1px solid #dce5dc}.note{background:#fff7df;padding:16px;border-radius:12px}img{width:100%;border:1px solid #dce5dc;border-radius:12px}figure{margin:18px 0}figcaption{font-size:14px;color:#53665b}.tag{background:#e6f1e6;padding:5px 12px;border-radius:20px;display:inline-block}@media(max-width:650px){main{padding:14px}section,header{padding:18px}h1{font-size:26px}}
    </style><main><header><span class="tag">2026-10-26 · 源码已更新</span><h1>整理不重复，引用读得清</h1><p>本轮改善知识结构的学习路径：找回正确的整理任务，避免旧请求打断新面板；阅读关系和原文时正常显示公式；重新整理不另建通读任务。</p></header>
    <section><h2>改动与实际效果</h2><table><tr><th>原来的问题</th><th>现在的处理</th></tr>
    <tr><td>同一份阅读记录被不同对话使用时，可能认错暂停任务。</td><td>同时核对项目、来源对话、阅读记录、AI 服务、模型和推理强度。已暂停任务要点击继续才运行。</td></tr>
    <tr><td>旧请求在关闭面板后才返回，可能覆盖新面板或解除新任务的按钮锁定。</td><td>每次返回都核对原面板和学习范围；旧任务仍在后台完成，但不能占用新面板。</td></tr>
    <tr><td>点重新整理会多建一个通读任务。</td><td>沿用已完成的阅读记录，知识结构接口仍校验原资料版本；需要重整的仅是结构本身。</td></tr>
    <tr><td>引用、关系理由和边界中的公式显示为代码。</td><td>使用本地 Markdown 和公式渲染；来源窗口同时提供正常排版与原始文字对照，不修改保存的引句。</td></tr>
    <tr><td>当前模型与另一模型的历史结构可能混在一起。</td><td>面板查询明确限定服务、模型和推理强度；当前选择没有结构时说明尚未整理，不自动花费模型请求。</td></tr></table></section>'''
    page+=f'<section><h2>验证结果</h2><p><strong>{gate["tests"]["total"]} 项相关 Python 测试、{count} 项前端测试通过，无失败或跳过。</strong>实际窗口完成五组操作：不接管其他对话的暂停任务；正常显示引用、关系和边界公式；原文排版与代码对照；重整不重复通读；保留草稿返回导师并继续原任务。</p><p>使用 2 次受控结构请求、0 次外部模型请求。重整前后没有增加通读任务；另一对话继续自己的暂停任务时复用未变的结构，没有新增模型请求。没有生成习题、自动发送聊天或增加掌握分数。</p><p><a href="../{GATE.name}/command.json">Python 回归与源码哈希</a> · <a href="../{GATE.name}/node-tests.log">前端测试记录</a> · <a href="../{UI.name}/ui-report.json">实际窗口记录</a> · <a href="verification.json">汇总记录</a></p></section>'
    page+='<section><h2>怎样打开验收</h2><p>先从 Windows 托盘退出旧版软件，再双击 <a href="../../验收最新版.vbs">验收最新版.vbs</a>。在学习对话选好资料并完成通读，打开“知识结构”。关闭、切换对话再回来，检查显示的是本对话任务。点“重新整理”后，可到成果任务区确认没有额外通读任务。</p><p>查看知识点的引用、关系及边界，公式应正常显示。点击来源，展开“查看原始文字（含公式代码）”可核对原文。点“带回原导师继续讲解”只会补入草稿，等你发送才调用导师。</p><p class="note">本轮未重新打包。已经交付的 0.4.5 安装器和源码压缩包保留为那次发布的快照，不包含这一轮改动。</p></section>'
    page+='<section><h2>实际窗口截图</h2><p>以下为合成测试资料。图中显式插入的 script 字样用于确认内容只被当作文字，不会执行；不是日常教学输出示例，也不是教学质量评分。</p>'
    for name,caption in [('math-structure','知识点引用、关系理由和边界使用正常数学排版。'),('math-original','来源可以排版阅读，同时保留原始文字供核对。'),('own-paused-task','切回本对话后找到自己的暂停任务，点击继续才处理。')]:
        assert (UI/(name+'.png')).is_file()
        page+=f'<figure><img src="../{UI.name}/{name}.png" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)}</figcaption></figure>'
    page+='</section><section><h2>边界</h2><p>本轮验证本机桌面与相关后端，不是外部模型教学质量比较，也没有重做安卓实机、真实大型书籍或整机内存峰值测试。知识结构整理不会据此证明你已经掌握；原文件改变时，仍需通过原有版本检查。</p></section></main></html>'
    target=OUT/'知识结构接续与公式阅读验收.html';target.write_text(page,encoding='utf-8');print(target)

if __name__=='__main__':main()
