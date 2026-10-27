"""Acceptance for cause-evidence sufficiency and multiline quotation boundaries."""
import hashlib
import html
import json
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/homework-evidence-final-20261026-3'
UI=ROOT/'build/homework-evidence-ui-20261026-3'
OUT=ROOT/'build/homework-evidence-acceptance-20261026'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate,ui,flow=load(GATE/'command.json'),load(UI/'ui-report.json'),load(UI/'evidence-gate.json')
    assert gate['exit_code']==0 and gate['source_frozen']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    cases=ET.parse(GATE/'regression.xml').getroot().findall('.//testcase')
    targeted=[case for case in cases if case.get('classname')=='tests.test_homework_evidence']
    assert len(targeted)==28
    before=ET.parse(ROOT/'build/homework-evidence-before-20261026.xml').getroot().findall('.//testcase')
    cache=ET.parse(ROOT/'build/homework-evidence-cache-before-20261026.xml').getroot().findall('.//testcase')
    assert len(before)==7 and len(cache)==1 and all(case.find('failure') is not None for case in before+cache)
    assert ui['passed'] and not ui['console_errors'] and ui['external_model_requests']==0
    assert flow['status']=='awaiting_causes' and flow['first_confidence']=='uncertain'
    assert not flow['feedback_registered'] and flow['error_insights']==0 and flow['model_requests']==3
    for name,digest in gate['production_after'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    OUT.mkdir(exist_ok=True)
    receipt={'passed':True,'regression':gate['tests'],'targeted_checks':len(targeted),'native_checks':len(ui['checks']),
        'source_sha256':gate['production_after'],'reproduced_evidence_failures':7,'reproduced_cache_failure':1,
        'controlled_model_requests':3,'external_model_requests':0,'real_user_data_modified':False,
        'packaged':False,'physical_android':False,'receipts':{'gate':str(GATE/'command.json'),
            'ui':str(UI/'ui-report.json'),'flow':str(UI/'evidence-gate.json')}}
    (OUT/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    def link(path,label):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(label)+'</a>'
    def picture(name,phone=False):return '<figure'+(' class="phone"' if phone else '')+'><img alt="'+html.escape(name)+'" src="'+html.escape((UI/(name+'.png')).as_uri(),quote=True)+'"><figcaption>实际界面、隔离数据。故意设置过度自信的受控模型来测试保护，不代表真实模型整体质量。</figcaption></figure>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>错因依据与作答引用验收</title><style>*{box-sizing:border-box}body{max-width:1100px;margin:36px auto;padding:0 22px 60px;background:#f2f5ee;color:#243d32;font:16px/1.9 system-ui,"Microsoft YaHei",sans-serif}header,section{padding:26px 32px;margin:20px 0;background:#fffefa;border:1px solid #d9e2d6;border-radius:18px}h1{line-height:1.4}.label,figcaption{font-size:12px;color:#58705f}a{color:#28664b}img{max-width:100%;border:1px solid #ceddce;border-radius:12px}.phone img{max-width:320px}figure{margin:18px 0}li{margin:8px 0}.notice{padding:15px 18px;background:#e8f0e5;border-radius:12px}@media(max-width:600px){body{padding:0 12px}header,section{padding:18px}}</style><header><div class="label">2026-10-26 · 源码更新 · 错因讲解的依据</div><h1>先分清“哪里错”与“为什么错”</h1><p>只给最终答案，通常不足以定位错误发生在哪一步。多行作答作为证据时，也应始终显示在引用范围内。</p></header>
<section><h2>复现与修复</h2><p>“答案是4”“我选B”、带Markdown或公式的最终结果，曾绕过仅识别纯数字的检查，模型可将猜测错因标成有依据。本机识别范围现在覆盖这些明确的短结论；遇到这类输入会保留原作答与评分，先询问当时的思路。未有学生自报时，不将其写成确定的粗心、概念或方法问题。</p><p class="notice">不会更改原答案或分数。2+3=4等可核对步骤、明确推理与编程短代码保留原有分析路径；学生问卷的有效引句仍标为自报，而非独立证实的原因。</p><p>另一处问题是证据引用只在第一行加了引用符号。现在每一行（包括空行、标题）都保持来源格式，学生笔记不会变成导师自己的标题或段落。实际Word导出检查确认源引句使用Source Quote样式。</p></section>
<section><h2>旧任务也需要经过新检查</h2><p>完成第一轮修复并通过317项回归后，继续复现到旧整阶段缓存可能绕过新检查。最终补讲阶段键带上诊断规则版本，单题复用也升级；未完成的旧任务重新核对依据。导师内部回看协议同步升级，避免继续带入旧引用格式。已交付文档与已有画像没有批量重写或清理。</p></section>'''
    page+='<section><h2>电脑端：结论不足时先询问</h2>'+picture('电脑端结论不足先询问')+'</section>'
    page+='<section><h2>多行引用保持清楚边界</h2>'+picture('电脑端多行作答仍为引用')+picture('手机端多行作答仍为引用',True)+'</section>'
    page+='<section><h2>手机端：同一份待澄清问卷</h2>'+picture('手机端结论不足先询问',True)+'</section>'
    page+='<section><h2>最终验证</h2><ul><li>'+str(gate['tests']['total'])+'项关联回归全通过，0失败、0错误、0跳过；6个生产文件指纹一致。</li><li>28项专门检查：中英文短结论、公式／单位／选项、明确步骤、编程例外、学生自报、真实Word来源样式、完整问卷流程，以及旧缓存绕过。</li><li>'+str(len(ui['checks']))+'组实际电脑／配对HTTPS手机操作通过，包含320px深色和逐题回看。</li><li>实际提交“答案是4”后等待问卷，没有交付猜测的错因文档、没有新错因画像；3次受控模型请求，云调用0次。</li></ul><p>第一轮回归脚本误用了不存在的测试文件名，测试未启动；第一轮UI脚本未处理引用块开头的换行，定位失败。两处验收脚本均修正并保留原日志，最终凭据来自当前源码。最终回归是在旧阶段缓存修复后重新执行。</p><p>本机规则只识别明确的短结论，不作数学判分，也不能保证所有语义误诊均被发现。无额外AI审查轮次，但旧未完成补讲可能需要按新规则重核。合成保护测试不证明整体讲解质量、真实模型水平、实体安卓或Word实际分页。</p></section>'
    page+='<section><h2>打开方式</h2><p>从Windows托盘完全退出旧版，再双击 '+link(ROOT/'验收最新版.vbs','验收最新版.vbs')+'。本轮未重新打包；0.4.4安装包不包含本次源码修复。</p><p>'+link(OUT/'result.json','验收索引')+' · '+link(GATE/'command.json','最终回归与源码指纹')+' · '+link(UI/'ui-report.json','两端实际操作')+' · '+link(UI/'evidence-gate.json','问卷与画像边界凭据')+'</p></section></html>'
    path=OUT/'错因依据与作答引用验收.html';path.write_text(page,encoding='utf-8');print(path)


if __name__=='__main__':main()
