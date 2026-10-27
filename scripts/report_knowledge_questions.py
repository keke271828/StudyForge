import hashlib,html,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/knowledge-questions-final-20261026-2'
UI=ROOT/'build/knowledge-questions-ui-20261026-4'
OUT=ROOT/'build/knowledge-questions-acceptance-20261026'
def main():
    gate=json.loads((GATE/'command.json').read_text(encoding='utf-8'));ui=json.loads((UI/'ui-report.json').read_text(encoding='utf-8'))
    assert gate['exit_code']==0 and gate['source_frozen'] and not any(gate['tests'][k] for k in ('failure','error','skipped'))
    for name,digest in gate['production_after'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    assert ui['passed'] and ui['external_model_requests']==0 and not ui['console_errors']
    log=(GATE/'node-tests.log').read_text(encoding='utf-8-sig');assert re.search(r'# fail 0\b',log)
    count=int(re.search(r'# tests (\d+)',log)[1]);OUT.mkdir(exist_ok=True)
    (OUT/'verification.json').write_text(json.dumps({'python':gate,'node_tests':count,'native':ui,'packaged':False},ensure_ascii=False,indent=2),encoding='utf-8')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>知识联系定向追问与学习证据验收</title><style>*{box-sizing:border-box}body{margin:0;background:#f2f4ee;color:#203b31;font:16px/1.85 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1100px;padding:36px 22px;margin:auto}section,header{background:#fffef9;border:1px solid #dce6da;border-radius:20px;padding:26px;margin-bottom:20px}h1{font-size:32px;line-height:1.35}h2{font-size:22px}a{color:#17624d}th,td{padding:13px;text-align:left;vertical-align:top;border-bottom:1px solid #e1e7dc}table{border-collapse:collapse;width:100%}img{width:100%;border:1px solid #dce6da;border-radius:12px}figure{margin:20px 0}figcaption{font-size:14px;color:#596e60}.note{padding:15px;background:#fff5dc;border-radius:12px}@media(max-width:650px){main{padding:14px}section,header{padding:18px}h1{font-size:26px}}</style><main>
    <header><p>2026-10-26 · 源码更新</p><h1>从看到联系，走到讲清理由</h1><p>在知识结构中选中一条联系，就能把具体疑问和原文位置带回同一导师。保留原草稿，核对后再发送。</p></header>
    <section><h2>四种联系，四种追问重点</h2><table><tr><th>关系</th><th>带回导师后要讲清什么</th></tr><tr><td>论证支持</td><td>目标与已知条件、关键转化为什么想到、每一步依据，以及遗漏的条件。</td></tr><tr><td>建议前置</td><td>具体在哪一步用到前一个知识点；建议不代表学生不会，也不是唯一顺序。</td></tr><tr><td>概念对比</td><td>定义、判别方法、容易混淆之处和恰当的具体例子。</td></tr><tr><td>知识类比</td><td>真实共同结构、对应关系与不适用条件；联系不成立时明确纠正，不强行跨学科。</td></tr></table></section>
    <section><h2>怎样使用</h2><ol><li>先退出 Windows 托盘旧版，再打开 <a href="../../验收最新版.vbs">验收最新版.vbs</a>。</li><li>在学习对话选好资料，完成通读，打开“知识结构”。</li><li>查看某条关系，点击“请导师讲清这条联系”。问题和可读的原文位置会补入聊天草稿。</li><li>修改或补充自己的卡点，再点击“发送”。准备草稿和切换对话不会调用导师。</li></ol><p>同一问题不会重复插入；图谱变更或资料切换后，旧按钮不能改写新草稿。原文短引与 AI 整理理由分开，并明确要求回查原资料。</p><p class="note">本轮未打包。已经交付的 0.4.5 安装器和源码 zip 不包含本轮改动。</p></section>'''
    page+=f'<section><h2>验证结果</h2><p><strong>{gate["tests"]["total"]} 项 Python 相关测试、{count} 项前端测试通过。</strong>实际窗口完成四组验收：定向问题及原文条件；草稿保留、去重与对话隔离；只在明确发送后请求原导师；图谱参考排除在学生理解候选证据之外。</p><p>共 1 次受控结构请求、1 次受控导师请求，0 次外部模型请求。没有自动出题或增加掌握分数。随附引用使用可读文字，不包含内部 source_id、节点编号或 JSON 参数。</p><p><a href="../{GATE.name}/command.json">Python 回归与源码校验</a> · <a href="../{GATE.name}/node-tests.log">前端记录</a> · <a href="../{UI.name}/ui-report.json">实际窗口记录</a> · <a href="verification.json">汇总记录</a></p></section><section><h2>实际窗口</h2><p>图中 AI_REFERENCE_ONLY 是专门放入引用内容的测试标记，用于验证它不会变成学生自己的理解证据。以下为合成资料和受控回复，不是模型教学质量样例。</p>'
    for name,caption in [('relation-question','论证支持使用自己的条件标题；追问按钮能滚动到可见区域。'),('saved-question-draft','保留原问题，再补入可读的联系与原文位置；此时没有调用导师。'),('tutor-followup','明确点击发送后，原导师收到问题和原文并返回排版回答。')]:
        assert (UI/(name+'.png')).is_file()
        page+=f'<figure><img src="../{UI.name}/{name}.png" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)}</figcaption></figure>'
    page+='</section><section><h2>验证范围</h2><p>这次验证桌面操作、信息传递和画像证据边界，不证明所有模型都会提高教学质量。没有重测安卓实机、实际大型视频或整机内存峰值。引用块不作为学生理解证据；学生的问题仍只是学习线索，不自动证明能力高低。</p></section></main></html>'
    target=OUT/'知识联系定向追问与学习证据验收.html';target.write_text(page,encoding='utf-8');print(target)
if __name__=='__main__':main()
