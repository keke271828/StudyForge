"""Publish only verified local receipts for the feedback citation reader."""
from pathlib import Path
import hashlib
import html
import json

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/'build/lesson-passage-math-ui-20261025-7'
GATE=ROOT/'build/lesson-passage-math-final-20261025-3'
OUT=ROOT/'build/lesson-passage-math-acceptance-20261025'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate=read(GATE/'command.json');ui=read(UI/'ui-report.json')
    mapping=read(UI/'source-mapping-checks.json');widget=read(UI/'widget-checks.json');keyboard=read(UI/'widget-report.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and not any(gate['tests'][k] for k in ('failure','error','skipped'))
    assert ui['passed'] and not ui['console_errors'] and ui['external_model_requests']==0 and ui['model_requests']==3
    assert mapping['passed'] and widget['passed'] and keyboard['passed']
    for path,digest in gate['production_after'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest,path
    OUT.mkdir(exist_ok=True)
    receipt={'passed':True,'regression':gate['tests'],'source_sha256':gate['production_after'],
        'native_ui_checks':len(ui['checks']),'source_mapping_cases':len(mapping['cases']),
        'widget_cases':len(widget['cases']),'native_keyboard_checks':len(keyboard['checks']),
        'controlled_model_calls':3,'external_model_calls':0,'packaged':False,
        'receipts':{'gate':str(GATE/'command.json'),'ui':str(UI/'ui-report.json'),
            'mapping':str(UI/'source-mapping-checks.json'),'widget':str(UI/'widget-checks.json'),
            'keyboard':str(UI/'widget-report.json')},
        'limits':['Synthetic saved lessons and controlled tutor responses; no new model-quality measurement.',
                  'Real desktop renderer and paired HTTPS browser; no physical Android touch acceptance.',
                  'Existing 0.4.4 installer is unchanged. Long sections remain paged.']}
    (OUT/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    escape=html.escape
    def link(path,label):return '<a href="'+escape(path.as_uri(),quote=True)+'">'+escape(label)+'</a>'
    picture=lambda name:'<img alt="'+escape(name)+'" src="'+escape((UI/(name+'.png')).as_uri(),quote=True)+'">'
    page=r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>讲解反馈原句公式与精确引用验收</title><style>*{box-sizing:border-box}body{max-width:1120px;margin:38px auto;padding:0 24px 50px;background:#f2f5ee;color:#253d32;font:16px/1.9 system-ui,"Microsoft YaHei",sans-serif}header,section{padding:26px 32px;background:#fffefa;border:1px solid #dbe4d8;border-radius:18px;margin:20px 0}h1{line-height:1.4}.label{color:#52765d;font-size:12px;letter-spacing:1px}a{color:#23694b}img{max-width:100%;height:auto;border:1px solid #cad9cb;border-radius:12px}pre{background:#edf1e7;padding:16px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere}.phone img{max-width:320px}li{margin:8px 0}@media(max-width:600px){body{padding:0 12px}header,section{padding:20px}}</style>
<header><div class="label">2026-10-25 · 源码改进 · 真实界面与独立数据</div><h1>在讲解反馈里也能正常读公式，<br>再准确指出卡住的一步</h1><p>补齐“理解反馈／内容核对”的历史讲解选段阅读，保留原文模式。这里查看的是历史AI回答，不是教材原文，也不是你的作答。</p></header>
<section><h2>这轮改变了什么</h2><ul><li>默认阅读Markdown和正常公式，保留“原文 · Markdown”。所选引用也正常排版。</li><li>选到公式一小部分时，保存完整原式；重复句按实际位置定位，不取第一个同名句。</li><li>7000字符以内的短节最多拼两次相邻读取，核对同文档、同章节、同版本，避免证明中的公式被4000字符分页切开。</li><li>长节继续按需分页，换页回到新片段开头；读取未完成时不使用旧片段误选。</li><li>手机窄屏将“使用选中原句”独占一行，刷新后恢复引用与公式。</li><li>只阅读和选句不调用模型；补充疑问并提交后，才交给原对话导师回应。</li></ul><p>原来看到的源码示例：</p><pre>\(\varepsilon=\frac{b-a}{2}\)</pre></section>'''
    page+='<section><h2>电脑：公式作为完整原句进入补讲</h2>'+picture('电脑端补讲原句公式')+'<p>截图来自合成的分页材料，目标公式跨过第4000字符，用于验证排版与位置；不是教学质量样本。</p></section>'
    page+='<section class="phone"><h2>手机：窄屏显示与引用恢复</h2>'+picture('手机端补讲原句公式')+'</section>'
    page+='<section><h2>实际验证</h2><ul><li>'+str(gate['tests']['total'])+'项相关回归通过，最终4个生产文件指纹一致。</li><li>'+str(len(ui['checks']))+'组电脑／配对HTTPS手机流程，'+str(len(mapping['cases']))+'项共用源文定位，'+str(len(widget['cases']))+'项控件边界和'+str(len(keyboard['checks']))+'项原生键盘检查通过。</li><li>3次受控模型请求、0次真实云模型请求。选段与查看不生成题目、不新增知识分数。</li><li>测试脚本问题和布局调整期间被指纹门禁拒绝的记录均保留，不将它们记为最终通过。</li></ul><p>本轮未打包，上一轮0.4.4安装包保持原内容。未进行真实模型教学质量、实体安卓触控或全软件性能评测。</p></section>'
    page+='<section><h2>怎样现在验收</h2><p>先从托盘完全退出旧版，再双击 '+link(ROOT/'验收最新版.vbs','验收最新版.vbs')+' 打开源码版，不需要打开CMD。</p><ol><li>打开一份已生成讲解的“理解反馈”。</li><li>展开“卡在哪一节或哪句话”，选章节，点击“查看本节原句”。</li><li>读公式，选一小部分并点“使用选中原句”，再填自己的疑问。</li><li>需要时再提交；仅查看不会请求AI。</li></ol><p>'+link(OUT/'result.json','完整验收索引')+' · '+link(GATE/'command.json','最终回归与源码指纹')+' · '+link(UI/'ui-report.json','两端流程记录')+'</p></section></html>'
    result=OUT/'讲解反馈原句公式与精确引用验收.html'
    result.write_text(page,encoding='utf-8')
    print(result)


if __name__=='__main__':main()
