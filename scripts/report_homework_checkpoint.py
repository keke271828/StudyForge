"""Publish recovery evidence only after the final source-frozen gate passes."""
import hashlib
import html
import json
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/homework-checkpoint-final-20261026'
UI=ROOT/'build/homework-checkpoint-ui-20261026-2'
OUT=ROOT/'build/homework-checkpoint-acceptance-20261026'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate,ui,seed,flow=load(GATE/'command.json'),load(UI/'ui-report.json'),load(UI/'seed-evidence.json'),load(UI/'checkpoint-evidence.json')
    assert gate['exit_code']==0 and gate['source_frozen']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    cases=ET.parse(GATE/'regression.xml').getroot().findall('.//testcase')
    targeted=[case for case in cases if case.get('classname')=='tests.test_homework_checkpoint']
    assert len(targeted)==15 and any(case.get('name','').startswith('test_fresh_python_process') for case in targeted)
    before=ET.parse(ROOT/'build/homework-checkpoint-before-20261026.xml').getroot().findall('.//testcase')
    assert len(before)==2 and all(case.find('failure') is not None for case in before)
    assert ui['passed'] and not ui['console_errors'] and ui['external_model_requests']==0
    assert not seed['phase_cache_present'] and seed['grade_model_requests']==2
    assert flow['job']['status']=='completed' and flow['submissions']==1 and flow['model_requests']==1
    assert all(flow[key] for key in ('submission_unchanged','mastery_unchanged','assessment_events_unchanged','feedback_registered'))
    for name,digest in gate['production_after'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    OUT.mkdir(exist_ok=True)
    receipt={'passed':True,'regression':gate['tests'],'targeted_checks':len(targeted),'native_checks':len(ui['checks']),
        'source_sha256':gate['production_after'],'reproduced_failures':2,
        'controlled_grade_requests_before_interruption':2,'controlled_requests_after_resume':1,
        'external_model_requests':0,'fresh_python_process_verified':True,'packaged':False,
        'real_user_data_modified':False,'physical_android':False,
        'receipts':{'gate':str(GATE/'command.json'),'ui':str(UI/'ui-report.json'),
            'seed':str(UI/'seed-evidence.json'),'resume':str(UI/'checkpoint-evidence.json')}}
    (OUT/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    def link(path,label):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(label)+'</a>'
    def picture(name,phone=False):return '<figure'+(' class="phone"' if phone else '')+'><img alt="'+html.escape(name)+'" src="'+html.escape((UI/(name+'.png')).as_uri(),quote=True)+'"><figcaption>隔离数据的实际界面。题目、评分与补讲由受控测试产生，不是实际学生成绩或真实模型质量样本。</figcaption></figure>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>评分保存与中断续做验收</title><style>*{box-sizing:border-box}body{max-width:1100px;margin:36px auto;padding:0 22px 60px;background:#f2f5ee;color:#243d32;font:16px/1.9 system-ui,"Microsoft YaHei",sans-serif}header,section{padding:26px 32px;margin:20px 0;background:#fffefa;border:1px solid #d9e2d6;border-radius:18px}h1{line-height:1.4}.label,figcaption{font-size:12px;color:#58705f}a{color:#28664b}img{max-width:100%;border:1px solid #ceddce;border-radius:12px}.phone img{max-width:320px}figure{margin:18px 0}li{margin:8px 0}.notice{padding:15px 18px;background:#e8f0e5;border-radius:12px}@media(max-width:600px){body{padding:0 12px}header,section{padding:18px}}</style><header><div class="label">2026-10-26 · 源码更新 · 学习记录一致性</div><h1>评分已经保存，就从未完成的补讲接着做</h1><p>修复异常中断后“已有成绩，却无法继续”的恢复缺口。能核实对应关系的评分直接复用，原成绩与掌握度不因继续任务再次更新。</p></header>
<section><h2>修复前的两种失败</h2><p>普通习题和JavaScript作业都完成评分后，在外层阶段缓存写入前模拟异常。成绩已存在，但任务继续时重新进入评分入口，分别遇到“已经提交”或“已经完成批改”，无法生成后续讲解。两个修复前用例均失败，原始XML已保留。</p><p class="notice">现在成绩、原提交关联、掌握度和测评证据在同一事务中保存。恢复时严格核对题单版本、提交编号、原答案、评分内容与数值；不搜索“最近一次成绩”来代替。学习证据写入失败时，这次评分整体回滚。</p></section>
<section><h2>现在怎样继续</h2><ol><li>异常中断后，在工作台的作业历史找到原记录，点“重试批改”。</li><li>软件核对已经保存的评分，匹配时只补做缺失的讲解和导出。</li><li>原题解析仍可查看；完成后可按题回看补讲，或在手机直接下载DOCX。</li><li>主动点“重新复核原作答”仍会进行评分复核，与恢复未完成步骤区分；缺少关联依据的旧记录不会被猜测恢复。</li></ol></section>'''
    page+='<section><h2>电脑端：原失败记录与恢复后的补讲</h2>'+picture('电脑端中断记录与重试入口')+picture('电脑端恢复后逐题补讲')+'</section>'
    page+='<section><h2>手机端：同一份恢复结果</h2>'+picture('手机端恢复后逐题补讲',True)+'</section>'
    page+='<section><h2>最终验证</h2><ul><li>'+str(gate['tests']['total'])+'项关联回归全通过，0失败、0错误、0跳过；9个生产文件指纹一致。</li><li>15项专门检查，覆盖普通／编程恢复、事务回滚、10种缺失或不一致依据，以及新的Python进程恢复。</li><li>'+str(len(ui['checks']))+'组电脑／配对HTTPS手机操作通过；实际点击重试、逐题查看与下载DOCX。</li><li>UI准备评分2次受控请求；中断后恢复只用1次受控补讲请求。原提交仍为1条，提交编号、掌握度和测评证据计数保持不变；云模型请求0次。</li></ul><p>使用模拟中断后的持久化数据及新的Python进程验证恢复；未做真实断电、损坏磁盘、真实模型教学能力或实体安卓认证。没有增加真实用户成绩或画像。此次不保证任意旧记录或损坏记录都能恢复，也不把一次恢复当成新的学习测验。</p></section>'
    page+='<section><h2>打开方式</h2><p>从Windows托盘完全退出旧版，再双击 '+link(ROOT/'验收最新版.vbs','验收最新版.vbs')+'，无需CMD。本轮未重新打包，现有0.4.4安装包不包含此次源码更新。</p><p>'+link(OUT/'result.json','验收索引')+' · '+link(GATE/'command.json','最终回归与源码指纹')+' · '+link(UI/'seed-evidence.json','中断前保存状态')+' · '+link(UI/'checkpoint-evidence.json','恢复后状态')+' · '+link(UI/'ui-report.json','实际两端操作')+'</p></section></html>'
    path=OUT/'评分保存与中断续做验收.html';path.write_text(page,encoding='utf-8');print(path)


if __name__=='__main__':main()
