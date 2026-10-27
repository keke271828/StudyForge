"""Publish guarded-assessment acceptance from final immutable evidence."""
import hashlib
import html
import json
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/homework-inflight-final-20261026'
UI=ROOT/'build/homework-inflight-ui-20261026'
OUT=ROOT/'build/homework-inflight-acceptance-20261026'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate,ui,flow=load(GATE/'command.json'),load(UI/'ui-report.json'),load(UI/'inflight-evidence.json')
    before=ET.parse(ROOT/'build/homework-inflight-before-20261026.xml').getroot().findall('.//testcase')
    assert len(before)==3 and all(case.find('failure') is not None for case in before)
    assert gate['exit_code']==0 and gate['source_frozen']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert ui['passed'] and not ui['console_errors'] and ui['external_model_requests']==0
    assert ui['controlled_model_requests']==3 and flow['calls']==3
    assert flow['job']['status']=='failed' and flow['score_count']==1
    assert not flow['analysis_saved'] and not flow['feedback_registered']
    for name,digest in gate['production_after'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    OUT.mkdir(exist_ok=True)
    receipt={'passed':True,'regression':gate['tests'],'native_checks':len(ui['checks']),
        'source_sha256':gate['production_after'],'reproduced_failures':3,'controlled_model_requests':3,
        'external_model_requests':0,'synthetic_committed_scores':1,'real_user_data_modified':False,
        'packaged':False,'physical_android':False,
        'receipts':{'regression':str(GATE/'command.json'),'ui':str(UI/'ui-report.json'),
            'flow':str(UI/'inflight-evidence.json'),'before_fix':str(ROOT/'build/homework-inflight-before-20261026.xml')}}
    (OUT/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    def link(path,label):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(label)+'</a>'
    def picture(name,phone=False):return '<figure'+(' class="phone"' if phone else '')+'><img alt="'+html.escape(name)+'" src="'+html.escape((UI/(name+'.png')).as_uri(),quote=True)+'"><figcaption>真实界面、独立合成数据。40分是受控评分，不是实际学生成绩或真实模型能力样本。</figcaption></figure>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>处理中改题与批改交付验收</title><style>*{box-sizing:border-box}body{max-width:1100px;margin:36px auto;padding:0 22px 60px;background:#f2f5ee;color:#243d32;font:16px/1.9 system-ui,"Microsoft YaHei",sans-serif}header,section{padding:26px 32px;margin:20px 0;background:#fffefa;border:1px solid #d9e2d6;border-radius:18px}h1{line-height:1.4}.label,figcaption{font-size:12px;color:#58705f}a{color:#28664b}img{max-width:100%;border:1px solid #ceddce;border-radius:12px}.phone img{max-width:320px}figure{margin:18px 0}li{margin:8px 0}.notice{padding:15px 18px;background:#e8f0e5;border-radius:12px}@media(max-width:600px){body{padding:0 12px}header,section{padding:18px}}</style><header><div class="label">2026-10-26 · 源码更新 · 异步任务版本核对</div><h1>题单中途变化，停止本阶段交付</h1><p>补上客户端准备、评分阶段、补讲、容器判题和文档排版中的题单版本核对。保持正常题单原有的模型请求次数。</p></header>
<section><h2>修复前实际复现</h2><p>三个专门用例均失败：在补讲和排版结束前改题，任务仍交付批改文档；在代码审查期间改题，任务仍保存成绩。普通习题评分事务原先已有保护，本轮保留；代码评分新增同类事务保护。</p><p class="notice">现在检测到问题后明确停止本阶段。此前已正确提交的作答、已交付解析与已保存的原版成绩保留，不再发布这阶段的错因或混合批改文档。版本冲突不以重复模型请求重试。</p></section>
<section><h2>具体做法</h2><ul><li>对题干、参考解（包括编程测试代码）、难度与项目归属进行本机核对；正常的状态变化和重命名不被当成改题。</li><li>等待结束准备开始评分或补讲时重新核对，避免在已变更的暂停任务中继续消耗模型请求。</li><li>模型或排版返回后再次核对，再登记结果；代码成绩保存时，在同一数据库写入事务内核对。</li><li>恢复只读历史的逻辑继续使用提交时原版，新的批改仍需要当前版本匹配。</li></ul></section>'''
    page+='<section><h2>电脑端实际提交</h2><p>从“提交作业”填写两题并确认提交。受控服务在完成评分、开始补讲后修改难度。任务停止，保留一条此前已保存的原版成绩和原题解析，不保存本次补讲，也不登记批改文件。</p>'+picture('电脑端中途改题停止交付')+'</section>'
    page+='<section><h2>配对手机查看相同结果</h2>'+picture('手机端中途改题停止交付',True)+picture('手机端保留原解析',True)+'</section>'
    page+='<section><h2>最终验证</h2><ul><li>'+str(gate['tests']['total'])+'项关联回归全通过，0失败、0错误、0跳过；5个生产文件指纹一致。</li><li>13项专门检查，覆盖异步步骤改题、代码题干／参考实现／测试代码变化、正常流程和非重试分类。</li><li>'+str(len(ui['checks']))+'组电脑和配对HTTPS手机流程通过，含320px深色、历史按题回看和独立草稿。</li><li>实际UI流程共3次受控模型请求、0次外部模型调用。合成评分在改题前已正确保存；不把应保留的原评分当成多余写入。</li></ul><p>本轮未评估真实模型教学水平、真实Docker运行环境、实体安卓触控或全软件速度／内存。保护覆盖所测异步边界和代码评分事务，不宣称任意外部数据库工具写入的所有时序均已验证。排版后中断的文件不登记为已交付成果。</p></section>'
    page+='<section><h2>打开新版</h2><p>从Windows托盘完全退出旧版，再双击 '+link(ROOT/'验收最新版.vbs','验收最新版.vbs')+'。本轮更新在源码版，0.4.4安装包尚未包含本次修复。</p><p>'+link(OUT/'result.json','验收索引')+' · '+link(GATE/'command.json','最终回归与生产指纹')+' · '+link(UI/'ui-report.json','实际操作检查')+' · '+link(UI/'inflight-evidence.json','中途改题流程凭据')+'</p></section></html>'
    path=OUT/'处理中改题与批改交付验收.html';path.write_text(page,encoding='utf-8');print(path)


if __name__=='__main__':main()
