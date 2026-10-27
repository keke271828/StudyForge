"""Verify saved trials and publish a local report without private solutions."""
import hashlib
import html
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/parallel-exercise-review-20261015'
FOLDERS=('exercise-review-plans-20261015-1','exercise-review-long-20261015-1','exercise-review-leak-20261015-1')


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def esc(value):return html.escape(str(value))


def intervals(spans):
    from datetime import datetime
    values=[(datetime.fromisoformat(s['started_at']),datetime.fromisoformat(s['ended_at'])) for s in spans]
    events=sorted([(start,1) for start,_ in values]+[(end,-1) for _,end in values],key=lambda item:(item[0],item[1]))
    active=peak=0
    for _,delta in events:active+=delta;peak=max(peak,active)
    return peak,max(0,(min(end for _,end in values)-max(start for start,_ in values)).total_seconds())


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    candidate=[];candidate_records={};requests=0
    for folder in FOLDERS:
        base=ROOT/'build'/folder;config=read(base/'configuration.json')
        snapshot=base/'baseline-review.py'
        if not snapshot.exists():snapshot=ROOT/'build'/FOLDERS[0]/'baseline-review.py'
        assert digest(snapshot)==config['source_sha256']['studyforge/review.py']
        # The rejected candidate moved out of runtime; its bytes are preserved.
        assert digest(ROOT/'scripts/exercise_review_policy_candidate.py')==config['source_sha256']['studyforge/exercise_review_policy.py']
        for row in read(base/'results.json'):
            assert row['status']=='completed'
            records=read(base/row['record_file'])
            assert [json.loads(record['response']) for record in records]==row['model_reports']
            assert len(records)==row['audit_component_calls']==len(row['http_attempts'])
            assert all(trace['status']==200 and trace['finish']=='stop' for trace in row['http_attempts'])
            requests+=len(records);candidate_records[(row['case'],row['plan'])]=records
            candidate.append({'case':row['case'],'plan':row['plan'],'seconds':row['seconds'],
                'requests':len(records),'verdicts':[report['passed'] for report in row['model_reports']],
                'issues':[[issue['problem'] for issue in report['issues']] for report in row['model_reports']]})
    assert requests==22 and len(candidate)==16
    leak={row['plan']:row for row in candidate if row['case']=='subtle_answer_leak'}
    assert not all(leak['dual_high']['verdicts']) and all(leak['combined_high']['verdicts'])
    live=ROOT/'build/parallel-exercise-review-real-20261015-1'
    for file,sha in read(live/'source-hashes.json').items():assert digest(ROOT/file)==sha
    parallel=[];bodies={}
    baseline=candidate_records[('subtle_answer_leak','dual_high')]
    for row in read(live/'results.json'):
        assert row['status']=='completed' and row['audit_calls']==2 and len(row['spans'])==2
        peak,overlap=intervals(row['spans'])
        assert peak==(2 if row['parallel'] and row['limit']==2 else 1)
        assert (overlap>0)==(peak==2)
        assert not all(report['passed'] for report in row['reports'])
        for call in row['calls']:
            traces=call['http_attempts'];assert len(traces)==1
            trace=traces[0]
            assert trace['status']==200 and trace['requested_model']=='deepseek-flash' and trace['effort']=='high'
            stage=call['stage'];bodies.setdefault(stage,set()).add(trace['body_sha256'])
            old=next(item for item in baseline if item['user'].startswith(stage+'。'))
            assert (old['system'],old['user'])==(call['system'],call['user'])
        parallel.append({'label':row['label'],'parallel':row['parallel'],'limit':row['limit'],
            'seconds':row['wall_s'],'requests':row['audit_calls'],'peak':peak,'overlap_seconds':overlap,
            'verdicts':[report['passed'] for report in row['reports']],
            'issues':[[issue['problem'] for issue in report['issues']] for report in row['reports']]})
    assert len(parallel)==3 and all(len(hashes)==1 for hashes in bodies.values())
    requests+=6
    tests=ET.parse(ROOT/'build/exercise-review-parallel-regression.xml').findall('.//testcase')
    assert tests and not any(case.find(tag) is not None for case in tests for tag in ('failure','error','skipped'))
    ids={(case.get('classname'),case.get('name')) for case in tests}
    assert len(ids)==len(tests)
    ui=read(ROOT/'build/lesson-check-ui-20261015-3/ui-report.json')
    assert ui['passed'] and len(ui['checks'])==7 and ui['controlled_model_calls']==8 and ui['external_model_requests']==0
    assert not ui['console_errors']
    assert 'exercise_review_policy_candidate' not in (ROOT/'studyforge/review.py').read_text(encoding='utf-8')
    assert 'shell-v43' in (ROOT/'web/mobile/sw.js').read_text(encoding='utf-8')
    names={'valid_math':'正确数学题','flawed_math':'错误端点结论与不公平评分','flawed_causal':'因果过度推断与虚构题源',
        'valid_ascii':'合法 ASCII 输入与范围外担忧','frozen_long_math':'较长的原数学检查题','subtle_answer_leak':'题干暗示另一问结论'}
    plans={'dual_high':'原两项核查 · 高推理','combined_high':'合并候选 · 高推理','combined_low':'合并候选 · 低推理'}
    verdict=lambda values:' / '.join('通过' if value else '拦截' for value in values)
    cand_rows=''.join('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in
        (names[row['case']],plans[row['plan']],f"{row['seconds']:.2f} 秒",row['requests'],verdict(row['verdicts'])))+'</tr>' for row in candidate)
    labels={'serial_two':'关闭内部并行，上限 2','parallel_two':'开启内部并行，上限 2','parallel_one':'开启内部并行，上限 1'}
    parallel_rows=''.join('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in
        (labels[row['label']],f"{row['seconds']:.2f} 秒",row['requests'],row['peak'],f"{row['overlap_seconds']:.2f} 秒",verdict(row['verdicts'])))+'</tr>' for row in parallel)
    findings=''
    for row in candidate:
        issues=[issue for report in row['issues'] for issue in report]
        findings+=f'<details><summary>{esc(names[row["case"]])} · {esc(plans[row["plan"]])} · {esc(verdict(row["verdicts"]))}</summary>'
        findings+=('<ul>'+''.join('<li>'+esc(issue)+'</li>' for issue in issues)+'</ul>' if issues else '<p>本次没有报告实质问题；这不等于题目已经得到准确性认证。</p>')+'</details>'
    page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>双核查并行与候选对照</title><style>
    *{box-sizing:border-box}body{margin:0;background:#eeefe8;color:#203c33;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1360px;padding:32px 22px 70px;margin:auto}header,section{background:#fffefa;border:1px solid #d4dfd3;border-radius:22px;padding:28px;margin-bottom:22px}h1{font-size:clamp(28px,4vw,42px);line-height:1.35;margin:8px 0 20px}h2{font-size:24px;margin-top:0}.eyebrow{font-size:12px;letter-spacing:.15em;color:#537365;font-weight:700}.pills{display:flex;flex-wrap:wrap;gap:10px}.pills span{background:#e6eee3;border-radius:30px;padding:7px 14px}.notice{background:#e8eee1;padding:16px 20px;border-radius:14px}.caution{background:#f4ebda;color:#655026}.table{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:12px 13px;border-bottom:1px solid #dbe2d6;text-align:left;vertical-align:top}th{background:#eff2e7;white-space:nowrap}td{min-width:85px}details{padding:14px 16px;border:1px solid #dce3d5;border-radius:12px;margin:12px 0}summary{cursor:pointer;font-weight:600}li{margin:7px 0}a{color:#21644d}footer{font-size:13px;color:#4f675a}@media(max-width:600px){main{padding:14px 10px 40px}header,section{padding:20px 16px;border-radius:16px}h2{font-size:21px}}</style></head><body><main>
    <header><div class="eyebrow">STUDYFORGE · 2026-10-15 · 实际请求与界面验证</div><h1>保留两项核查，让独立步骤重叠</h1><p>先比较是否能减少核查，再根据漏检结果决定实现。合并方案虽然在一些样例更快，但漏掉了题干中的答案提示，因此留作开发实验，没有进入软件。</p><div class="pills"><span>28 次真实审查请求</span><span>同一 DeepSeek Flash / high</span><span>两项核查提示词不变</span><span>TEST_COUNT 项程序检查</span><span>7 项完整界面检查</span></div></header>
    <section><h2>本轮采用什么</h2><p>工作台选择“任务内部并行”后，普通题单的解析核查和成品核查可以在两个独立分支中同时运行。它们检查同一份已完成的独立解法和题目，各自保留原标准。独立解题、收集全部问题、修订及修订后重新求解仍按依赖推进。</p><p class="notice">默认值保持原设置。关闭开关，两项核查依次执行；开启且模型并发上限至少为 2 时允许重叠。上限为 1、全局串行或服务不能创建独立分支时仍依次执行。旧任务沿用原方式，新任务保存启动时选项。</p><p>电脑端的“补讲后检查 1 题”沿用当前开关；手机端继承保存的默认值。并行改变执行安排，不减少核查次数，也没有降低模型、推理强度或发布门槛。</p></section>
    <section><h2>同一输入的串行与并行实测</h2><div class="table"><table id="parallel"><thead><tr><th>执行选择</th><th>核查阶段总用时</th><th>请求</th><th>实际同时请求峰值</th><th>两项实际重叠</th><th>两项判定</th></tr></thead><tbody>PARALLEL_ROWS</tbody></table></div><p>六次请求按阶段比较，请求正文指纹完全相同；模型、推理强度、题目、参考解与独立解法保持一致。三种执行方式最终都拦截了同一处预设的答案提示。上限为 1 时，第二项请求排队，没有同时运行。</p><p class="notice caution">约 53.72 → 27.85 秒是这一个样例的核查部分，不是完整出题、讲解或视频任务的通用提速比例。每种执行方式仅一次，服务器状态、缓存与生成长度仍有差异。请求数量保持两次；没有证明总 token 降低，临时并行内存也可能更高，仍由统一上限约束。</p></section>
    <section><h2>为什么没有采用合并核查</h2><p>四个简单对照中，各方案均按预设通过正确题、拦截缺陷题，并驳回题意之外的输入担忧。较长的原数学检查题中，双核查另发现了评分要求超出题意的担忧，合并核查只报告了答案暗示。该长题最初标注为正确；人工检查后保留这一争议，没有把初始标签当作标准答案。</p><p>最后加入细微答案提示：“它与(1)的结果不同”，而两问结论本来都是学生需要独立判断的评分点。原两项核查中，成品核查发现问题；合并高推理候选却放行。这个漏检足以拒绝当前合并方案。低推理候选仅做过前四个简单控制，没有通过后续挑战，不采用。</p><div class="table"><table id="candidates"><thead><tr><th>样例</th><th>方案</th><th>总用时</th><th>请求</th><th>逐项判定</th></tr></thead><tbody>CANDIDATE_ROWS</tbody></table></div></section>
    <section><h2>原模型最终报告的问题</h2><p>下列仅展示核查结果与问题描述，不公开私有参考解、修订答案或模型思考正文。模型报告仍可能误判，问题数量不等于质量分数。</p>FINDINGS</section>
    <section><h2>程序与界面验收</h2><ul><li>串行、并行、上限 1、无独立分支服务回退均检查实际重叠，而非只检查标签。</li><li>两个报告按原顺序保留，修订前收集双方问题，修订后再次独立求解和双核查。</li><li>暂停后保存已完成步骤；一个分支失败时重试复用另一分支的结果；取消后关闭分支并释放名额。</li><li>隔离数据下实际电脑界面及配对 HTTPS 手机尺寸界面运行通过；8 次受控响应、0 次外部模型请求。检查当前资料不被改动、重复点击去重、刷新恢复、Word 下载和提交前答案隐藏。</li></ul><p>本轮不包含真实安卓设备、整本书、长视频或多任务总内存压力测试，也不能证明长期学习效果。教学提示词和生成模型没有调整；当前仅优化普通习题的两项独立核查，不推广为所有 AI 任务的性能结论。</p><p><a href="最终核验记录.json">查看最终核验记录</a> · <a href="不含私有答案的对照数据.json">查看脱敏对照数据</a></p></section><footer>所有评测使用隔离目录和合成题目，不写生产用户资料或设置。本轮为源码验收；原 0.4.3 安装包保持原内容。</footer></main></body></html>'''
    page=page.replace('TEST_COUNT',str(len(tests))).replace('PARALLEL_ROWS',parallel_rows).replace('CANDIDATE_ROWS',cand_rows).replace('FINDINGS',findings)
    target=OUT/'双核查并行与候选对照.html';target.write_text(page,encoding='utf-8')
    (OUT/'不含私有答案的对照数据.json').write_text(json.dumps({'candidate':candidate,'parallel':parallel},ensure_ascii=False,indent=2),encoding='utf-8')
    files=('studyforge/review.py','studyforge/exercises.py','studyforge/server.py','web/parallel.js','web/lesson_feedback.js',
        'web/help/guide.html','web/mobile/sw.js','scripts/export_teaching_policy.py','docs/AI导师提示词.md',
        'tests/test_parallel_exercise_reviews.py','scripts/smoke_lesson_check_ui.py','scripts/smoke_lesson_check_ui.js',
        'scripts/build_parallel_exercise_review_report.py','scripts/preview_parallel_exercise_report.js',
        'docs/普通习题双核查并行验收.md','docs/当前功能状态与待验收清单.md')
    record={'passed':True,'real_audit_requests':requests,'candidate_requests':22,'adopted_plan_probe_requests':6,
        'deduplicated_program_checks':len(tests),'ui_checks':len(ui['checks']),'controlled_ui_responses':8,
        'ui_external_model_requests':0,'merged_candidate_adopted':False,'reasoning_lowered':False,
        'both_audits_preserved':True,'original_request_templates_equal':True,'request_bodies_equal_across_modes':True,
        'actual_peaks':{row['label']:row['peak'] for row in parallel},'production_settings_written':False,
        'reasoning_text_saved':False,'public_report_contains_private_solutions':False,
        'html_sha256':digest(target),'source_sha256':{file:digest(ROOT/file) for file in files}}
    (OUT/'最终核验记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in record.items() if key!='source_sha256'},ensure_ascii=True))


if __name__=='__main__':main()
