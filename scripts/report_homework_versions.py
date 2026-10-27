"""Publish a reviewable receipt only after final regression and native UI pass."""
from pathlib import Path
import hashlib
import html
import json

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/'build/homework-version-ui-20261026-3'
GATE=ROOT/'build/homework-version-final-20261026'
OUT=ROOT/'build/homework-version-acceptance-20261026'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate,ui=load(GATE/'command.json'),load(UI/'ui-report.json')
    assert gate['exit_code']==0 and gate['source_frozen']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert ui['passed'] and not ui['console_errors']
    assert ui['controlled_model_requests']==ui['external_model_requests']==0
    syntax=json.loads((UI/'syntax-check.json').read_text(encoding='utf-8-sig'))
    assert len(syntax)==5 and all(item['passed'] for item in syntax)
    for name,digest in gate['production_after'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    OUT.mkdir(exist_ok=True)
    receipt={'passed':True,'regression':gate['tests'],'native_checks':len(ui['checks']),
        'source_sha256':gate['production_after'],'controlled_model_calls':0,'external_model_calls':0,
        'real_user_data_modified':False,'packaged':False,'physical_android':False,'syntax_checks':syntax,
        'receipts':{'regression':str(GATE/'command.json'),'ui':str(UI/'ui-report.json'),'syntax':str(UI/'syntax-check.json')}}
    (OUT/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    def link(path,label):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(label)+'</a>'
    def picture(name,phone=False):return '<figure'+(' class="phone"' if phone else '')+'><img alt="'+html.escape(name)+'" src="'+html.escape((UI/(name+'.png')).as_uri(),quote=True)+'"><figcaption>隔离数据的实际界面；题目和既有评分为合成样例，不用于评价模型教学能力。</figcaption></figure>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>作业原题版本与历史反馈验收</title><style>*{box-sizing:border-box}body{max-width:1100px;margin:36px auto;padding:0 22px 60px;background:#f2f5ee;color:#243d32;font:16px/1.9 system-ui,"Microsoft YaHei",sans-serif}header,section{padding:26px 32px;margin:20px 0;background:#fffefa;border:1px solid #d9e2d6;border-radius:18px}h1{line-height:1.4}.label,figcaption{font-size:12px;color:#58705f}a{color:#28664b}img{max-width:100%;border:1px solid #ceddce;border-radius:12px}.phone img{max-width:320px}figure{margin:18px 0}li{margin:8px 0}.notice{padding:15px 18px;background:#e8f0e5;border-radius:12px}@media(max-width:600px){body{padding:0 12px}header,section{padding:18px}}</style>
<header><div class="label">2026-10-26 · 源码更新 · 作业历史依据</div><h1>旧作答始终对应提交时的原题</h1><p>题单后来被改写、缩短或修改参考解时，按题回看使用提交时已经保存的题目版本，并显示清楚的版本提示。</p></header>
<section><h2>复现的问题</h2><p>旧错因问卷曾从题单的当前版本读取题干，再配上历史作答。题目改写后会错配，题数减少时还会出现 IndexError，影响作业列表读取。历史阅读器则直接拒绝变更题单，虽然原题版本其实已经保存，却无法按题继续学习。</p><p class="notice">修复后：原题、原作答、原参考解和原评分一起回看。版本不一致时停用旧问卷、重试和再练入口。不会把旧成绩套到新题上。</p></section>
<section><h2>怎样使用</h2><ol><li>在习题页或工作台的作业历史里找到已提交的题单。</li><li>出现“当前题单已变更”时，点击“按题回看”，选择原来的题号。</li><li>阅读原题、自己的作答与已交付反馈；点击“带题号回原对话”可继续追问。</li><li>原题版本损坏或缺失时会说明无法核实，可查看原先已交付的下载文档。未完整提交、未发布诊断和其他对话的记录仍按原有范围限制读取。</li></ol></section>'''
    page+='<section><h2>电脑端：版本说明和原题回看</h2>'+picture('电脑端原版本提示')+picture('电脑端旧题按题回看')+'</section>'
    page+='<section><h2>手机端：相同的原题和停用提示</h2>'+picture('手机端旧题按题回看',True)+picture('手机端旧问卷停用',True)+'</section>'
    page+='<section><h2>验证记录与范围</h2><ul><li>'+str(gate['tests']['total'])+'项关联回归通过，最终8个生产文件指纹保持一致；新增22项专门检查。</li><li>'+str(len(ui['checks']))+'组电脑与配对HTTPS手机操作通过，包含原题数保留、旧问卷停用、损坏版本、独立草稿和320px深色显示。</li><li>受控模型调用0次，真实云模型调用0次；回看没有新增作答成绩或知识评分。</li><li>原版本恢复仅用于阅读；批改、问卷写入和重试仍核对当前版本。已删除原题或对话不会被恢复为可读记录。</li></ul><p>首次专门测试有两处夹具问题：把正常工具审计当成了学习数据改动；删除题单被生产外键保护阻止。第二轮UI脚本错误等待已提交题单出现在答题下拉框，已改为核对真实历史入口。这些中间结果保留，不当成最终通过证据。</p><p>这次验收证明作业版本与界面行为，不证明模型整体教学水平、实体安卓触控或全软件性能。未对运行到一半时外部修改题单的所有时序作全面认证。</p></section>'
    page+='<section><h2>打开新版</h2><p>先从Windows托盘完全退出旧版，然后双击 '+link(ROOT/'验收最新版.vbs','验收最新版.vbs')+' 打开源码版，无需CMD。这轮没有重新打包；0.4.4安装包不包含此次源码修复。</p><p>'+link(OUT/'result.json','验收索引')+' · '+link(GATE/'command.json','最终回归与源码指纹')+' · '+link(UI/'ui-report.json','实际界面检查')+'</p></section></html>'
    path=OUT/'作业原题版本与历史反馈验收.html'
    path.write_text(page,encoding='utf-8');print(path)


if __name__=='__main__':main()
