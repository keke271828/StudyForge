"""Publish only verified local task-continuity evidence, not a teaching benchmark."""
import hashlib
import html
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/reading-restore-acceptance-20261026'
GATE=ROOT/'build/reading-restore-final-20261026'
UI=ROOT/'build/reading-restore-ui-20261026-4'
PRODUCTION=['studyforge/conversations.py','studyforge/server.py','web/task_controls.js','web/conversations.js',
            'web/app.js','web/knowledge.js','web/help/guide.html']

def main():
    gate=json.loads((GATE/'command.json').read_text(encoding='utf-8'))
    ui=json.loads((UI/'ui-report.json').read_text(encoding='utf-8'))
    syntax=json.loads((GATE/'syntax.json').read_text(encoding='utf-8-sig'))
    node=(GATE/'node-tests.log').read_text(encoding='utf-8-sig')
    assert gate['exit_code']==0 and gate['source_frozen'] and not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert ui['passed'] and ui['external_model_requests']==0 and not ui['console_errors']
    assert not syntax['failures'] and re.search(r'# fail 0\b',node) and re.search(r'# skipped 0\b',node)
    hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in PRODUCTION}
    assert all(gate['production_after'][name]==digest for name,digest in hashes.items())
    count=int(re.search(r'# tests (\d+)',node)[1]);OUT.mkdir(exist_ok=True)
    receipt={'python_tests':gate['tests'],'node_tests':count,'own_js_syntax':syntax['files'],'native':ui,
        'production_sha256':hashes,'scope':'本机隔离测试与受控模型；不是外部模型教学质量或整机内存基准'}
    (OUT/'verification.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    def link(path,title):
        href=(Path('../..')/path.relative_to(ROOT)).as_posix()
        return f'<a href="{html.escape(href)}">{html.escape(title)}</a>'
    def image(name,caption):
        assert (UI/(name+'.png')).is_file()
        return f'<figure><img src="../{UI.name}/{name}.png" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)}</figcaption></figure>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>通读进度恢复与对话隔离验收</title><style>
    *{box-sizing:border-box}body{font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif;color:#203b32;background:#f3f4ee;margin:0}main{max-width:1100px;margin:auto;padding:44px 24px}h1{font-size:34px;line-height:1.3}h2{font-size:23px}section,header{background:#fffef9;border:1px solid #dce5d9;border-radius:20px;padding:26px;margin:20px 0}a{color:#14634c}table{width:100%;border-collapse:collapse}td,th{padding:14px;text-align:left;vertical-align:top;border-bottom:1px solid #e3e7dd}p{margin:12px 0}.badge{display:inline-block;background:#e7f1e7;border-radius:20px;padding:5px 14px}img{width:100%;border:1px solid #dce5d9;border-radius:12px}figure{margin:20px 0}figcaption{color:#53665d;font-size:14px}.limits{background:#fff9e9}code{overflow-wrap:anywhere}@media(max-width:640px){main{padding:16px}header,section{padding:18px}h1{font-size:27px}table{font-size:14px}}
    </style><main><header><span class="badge">2026-10-26 · 本机隔离验收通过</span><h1>学习可以切走，再接着读</h1><p>本轮修复通读进度随对话恢复、后台任务不自动打开其他对话的题单，并缩小前端任务控制缓存。资料、聊天和完整成果仍保存在本机原有位置。</p></header><section><h2>这次改了什么</h2><table><tr><th>使用情景</th><th>现在的行为</th></tr><tr><td>通读未完成，切换项目或刷新界面</td><td>返回原对话后恢复同一任务的进度和按钮，不重复启动模型。</td></tr><tr><td>暂停后离开原对话</td><td>回来仍保持暂停；点“继续通读”才接着处理。</td></tr><tr><td>通读失败后重新打开对话</td><td>保留原任务和失败原因；临时错误保留重试入口，不把失败当作已理解。</td></tr><tr><td>另一个对话出题或批改完成</td><td>结果仍保存在来源对话及项目中，不自动展开其题单；本项目其他任务的通知会说明来源不同。</td></tr><tr><td>长期使用、多任务并行</td><td>前端任务控制缓存只留进度和按钮所需字段，排除讲解全文、答案、聊天与图片数据；旧结束记录最多缓存 128 条，完整历史仍可从服务端查看。</td></tr></table></section>'''
    page+=f'<section><h2>怎样自己验收</h2><p>先从 Windows 托盘退出旧版 StudyForge，再双击 {link(ROOT/"验收最新版.vbs","验收最新版.vbs")} 启动工作区版本。这轮未重新打包安装器。</p><ol><li>在一个学习对话勾选资料，点击“通读资料”。</li><li>切到另一个对话或项目，再切回来；检查进度仍在，任务 ID 没有变。也可以刷新界面。</li><li>暂停后切走，再回来点击“继续通读”；完成后点“阅读笔记”。不同对话的选材和聊天仍独立。</li></ol><p>使用指南按 F1；新增“通读时，可以切换对话或关闭窗口吗？”说明。</p></section>'
    page+=f'<section><h2>核验结果</h2><p><b>{gate["tests"]["total"]} 项 Python 相关回归、{count} 项前端测试、{syntax["files"]} 个自有 JavaScript 文件语法检查通过。</b></p><p>实际窗口跑了四组流程：跨项目恢复、完整界面重载、异步完成不串到别的对话、暂停后继续。共 1 次受控模型请求、0 次外部模型请求；两个通读任务复用同一份未改动阅读记录，没有增加掌握分数或重复登记阅读事件。</p><p>本次窗口流程结束时，任务控制缓存序列化后为 {ui["task_control_cache_bytes"]} 字节；这是缓存大小，不能当成整个软件的内存占用。</p><p>{link(GATE/"command.json","Python 回归与源码校验")} · {link(GATE/"node-tests.log","前端测试记录")} · {link(UI/"ui-report.json","实际窗口验收记录")} · {link(OUT/"verification.json","汇总证据")}</p></section>'
    page+='<section><h2>实际窗口截图</h2>'+image('running-restored','跨项目切回后，原通读任务继续显示 37% 和暂停入口。')+image('paused-restored','暂停任务切回后仍保持暂停，点击可见的“继续通读”按钮恢复。')+image('completed-notes-restored','回到原对话后可打开完成的阅读笔记，没有将笔记放入另一个对话。')+'</section>'
    page+='<section class="limits"><h2>这份验收的范围</h2><p>本轮验证本机桌面界面及后端恢复逻辑。完整退出应用后重新启动服务、安卓实机、真实大视频和大书并发内存峰值未在本轮重新测试。受控回复用于核验流程，不代表讲解质量评测；也没有据此声称所有性能问题都已解决。</p><p>仅隐藏到托盘时后台任务可以继续；电脑关机或真正退出程序会停止执行。原文件改变后，继续／重试仍需原有的版本核对，不会为了恢复进度而跳过。</p></section></main></html>'
    target=OUT/'通读进度恢复与对话隔离验收.html';target.write_text(page,encoding='utf-8')
    print(target)

if __name__=='__main__':main()
