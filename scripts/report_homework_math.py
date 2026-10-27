"""Collect real rendering and scope-isolation receipts for submitted-work UI."""
from pathlib import Path
import hashlib
import html
import json

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/'build/homework-math-ui-20261025-7'
GATE=ROOT/'build/homework-math-final-20261025-2'
OUT=ROOT/'build/homework-math-acceptance-20261025'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate,ui=read(GATE/'command.json'),read(UI/'ui-report.json')
    widget,scope=read(UI/'diagnosis-widget-checks.json'),read(UI/'followup-scope-checks.json')
    before=read(ROOT/'build/homework-math-ui-20261025-5/ui-report.json')
    assert 'contaminated a different conversation' in before['error']
    assert gate['exit_code']==0 and gate['source_frozen'] and not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert ui['passed'] and not ui['console_errors'] and ui['controlled_model_requests']==ui['external_model_requests']==0
    assert widget['passed'] and scope['passed'] and len(scope['cases'])==4
    for name,digest in gate['production_after'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    OUT.mkdir(exist_ok=True)
    receipt={'passed':True,'regression':gate['tests'],'source_sha256':gate['production_after'],
        'native_checks':len(ui['checks']),'diagnosis_cases':len(widget['cases']),'followup_scope_cases':len(scope['cases']),
        'controlled_model_calls':0,'external_model_calls':0,'draft_race_reproduced_before_fix':True,
        'packaged':False,'real_user_data_modified':False,
        'receipts':{'gate':str(GATE/'command.json'),'ui':str(UI/'ui-report.json'),
            'diagnosis':str(UI/'diagnosis-widget-checks.json'),'scope':str(UI/'followup-scope-checks.json'),
            'before_fix':str(ROOT/'build/homework-math-ui-20261025-5/ui-report.json')}}
    (OUT/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    def link(path,label):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(label)+'</a>'
    def picture(name,phone=False):return '<figure'+(' class="phone"' if phone else '')+'><img alt="'+html.escape(name)+'" src="'+html.escape((UI/(name+'.png')).as_uri(),quote=True)+'"><figcaption>合成资料与既有提交记录，展示界面行为，不是模型教学质量样本。</figcaption></figure>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>错因公式排版与追问对话隔离验收</title><style>*{box-sizing:border-box}body{max-width:1120px;margin:36px auto;padding:0 24px 60px;background:#f2f5ee;color:#243d32;font:16px/1.9 system-ui,"Microsoft YaHei",sans-serif}header,section{padding:28px 32px;margin:20px 0;background:#fffefa;border:1px solid #d9e2d6;border-radius:20px}h1{line-height:1.4}.label,figcaption{font-size:12px;color:#58705f}a{color:#28664b}img{max-width:100%;border:1px solid #ceddce;border-radius:12px}.phone img{max-width:320px}figure{margin:18px 0}li{margin:8px 0}.callout{padding:15px 18px;border-radius:12px;background:#e8f0e5}@media(max-width:600px){body{padding:0 12px}header,section{padding:20px}}</style><header><div class="label">2026-10-25 · 源码更新 · 隔离数据实际验收</div><h1>读清楚错因，再回原对话问具体那一题</h1><p>错因问卷、诊断理由和下一步说明正常排版公式与Markdown；学生作答片段保持原文。已有提交记录的题单改用按题回看，减少整份反馈复制。</p></header>
<section><h2>修复一个真实的草稿串入问题</h2><p>旧练习的“带回导师”在异步读取尚未返回时没有核对对话。如果这时切换对话，迟到的反馈会追加到新草稿。本轮先用实际切换复现，再加入项目、对话和切换标记检查，分别保护题单与成绩两次读取。</p><p class="callout">同一对话的旧记录仍可按原方式继续问；切换对话或项目后，迟到的旧反馈停止填入。不会自动发送问题。</p></section>
<section><h2>现在怎样使用</h2><ol><li>在习题页打开已提交题单，阅读正常排版的诊断与下一步。</li><li>有提交记录时点击“按题回看，再向导师追问”，选择具体题目。</li><li>点击返回原对话的按钮，保留原草稿，再补上自己的问题并发送。</li><li>遇到错因问卷时，先看导师的公式提问，再填写自己的实际思路；题目内容刷新也保留已写说明。</li></ol></section>'''
    page+='<section><h2>电脑端：已有诊断的公式排版</h2>'+picture('电脑端错因诊断公式')+'</section>'
    page+='<section><h2>手机端：错因提问清晰可读</h2>'+picture('手机端错因问卷公式',True)+'</section>'
    page+='<section><h2>最终验证</h2><ul><li>'+str(gate['tests']['total'])+'项相关回归通过，最终8个生产文件指纹保持一致。</li><li>'+str(len(ui['checks']))+'组两端流程、'+str(len(widget['cases']))+'项诊断渲染边界、4项异步追问范围检查通过。</li><li>满分不显示虚构错因，评分待核实不提前给诊断，异常旧诊断不使页面崩溃。</li><li>实际电脑、配对HTTPS手机与320px深色界面；受控及真实模型请求均为0，没有新增知识评分。</li></ul><p>本轮使用合成已提交记录，不代表真实模型批改能力提升，也不是实体安卓触控或全软件性能评测。</p></section>'
    page+='<section><h2>打开方式</h2><p>先从托盘完全退出旧版，再双击 '+link(ROOT/'验收最新版.vbs','验收最新版.vbs')+' 打开源码版，无需CMD。本轮未重新打包，现有0.4.4安装包保持上一轮内容。</p><p>'+link(OUT/'result.json','验收索引')+' · '+link(GATE/'command.json','最终回归和源码指纹')+' · '+link(UI/'ui-report.json','两端流程')+' · '+link(UI/'followup-scope-checks.json','异步切换检查')+'</p></section></html>'
    result=OUT/'错因公式排版与追问对话隔离验收.html';result.write_text(page,encoding='utf-8');print(result)


if __name__=='__main__':main()
