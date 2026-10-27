"""Publish bounded experiment findings without exposing private exercise answers."""
import hashlib
from html import escape as esc
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote,unquote,urlsplit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/repair-scope-acceptance-20261023'
GATE=ROOT/'build/repair-scope-final-20261022-2'
UI=ROOT/'build/repair-scope-ui-20261022-2'
LIVE=ROOT/'build/repair-scope-native-20261022-2'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def link(path,label):return '<a href="'+quote(os.path.relpath(path,OUT).replace('\\','/'),safe='/')+'">'+esc(label)+'</a>'


def main():
    gate=read(GATE/'command.json');ui=read(UI/'ui-report.json');live=read(LIVE/'report.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and gate['tests']['failure']==gate['tests']['error']==gate['tests']['skipped']==0
    assert all(sha(ROOT/name)==value for name,value in gate['production_after'].items())
    assert ui['passed'] and live['status']=='completed' and live['model_requests']==4
    assert not OUT.exists();OUT.mkdir()
    worksheet=read(LIVE/'student-worksheet.json');assert len(worksheet['questions'])==1 and not worksheet.get('solutions')
    word=Path(live['word_file'])
    from docx import Document
    prose='\n'.join(p.text for p in Document(word).paragraphs)
    assert worksheet['questions'][0]['question'] in prose
    assert all(token not in prose for token in ('PRIVATE_','repair_focus','参考解析','评分标准','repair_scope'))
    database=sqlite3.connect((LIVE/'data/studyforge.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    try:
        row=database.execute('SELECT solutions_json FROM exercise_sets WHERE id=?',(worksheet['id'],)).fetchone()
        reports=json.loads(row[0])[0]['generation_reviews']
        scoped=[r for r in reports if r['stage'] in ('解析核查','成品核查')]
        assert len(scoped)==2 and all(r['repair_scope']['version']==2 and r['repair_scope']['target_indices']==[0] for r in scoped)
        assert reports[0]['stage']=='独立解题' and 'repair_scope' not in reports[0]
    finally:database.close()
    # Public summaries include verdicts and metrics only; request/response bodies
    # contain private reference answers and remain unlinked audit files.
    groups=[]
    for number in (1,2,3):
        folder=ROOT/f'build/repair-scope-pairs-20261022-{number}'
        report=read(folder/'report.json');assert report['status']=='completed'
        groups.append({'round':number,'trials':report['trials'],'calls':report['calls']})
    trial_native=read(ROOT/'build/repair-scope-native-20261022-1/report.json')
    all_calls=[call for group in groups for call in group['calls']]+trial_native['calls']+live['calls']
    total_requests=len(all_calls);tokens=sum(call['usage']['total_tokens'] for call in all_calls)
    manual={
        'accepted':'只补原题、暂定错因和已交付补讲的私有核对数据；保持原审查轮数和通用教师规则。',
        'rejected':'额外的长篇前置／条件检查要求没有显示稳定优势，且对给定条件是否泄漏答案有误拦风险，未纳入最终实现。',
        'initial_pairs':'数学、社会科学两组新旧均指出预置实质缺陷并放行对应对照。物理组均未指出此前人工关注的点电荷条件／前置问题，反而拦截另一道带非零均匀场前提的题。该题初始参考解与评分标准较简略，可能影响判断。',
        'refined_pair':'补完整参考说明及评分点后，旧方案放行，长要求方案仍以泄漏答案为由拦截。题目中一个判断可直接读出，但整体与局部的比较仍需论证，是否阻止发布存在教学取舍；不据此宣称准确率。',
        'minimal_pair':'最终仅补原始范围数据的方案与基线均放行两题；仍没有指出原点电荷样例的条件／前置问题。只证明没有在此样例新增该项拦截，不证明漏检已解决。',
        'native':'最终源码实跑只交付所选一题，使用原资料已有的外部电荷影响局部场情境，没有要求计算点电荷场。独立求解和两项核查的主结论一致。独立解题提出盒子是否为导体的疑点，两位核查员依据“仅根据这些条件”驳回；改称假想闭合曲面会更清楚。原题保持不改写。',
        'limits':'合成作答、人工评分及有限样例，不是全面质量、难度等价、速度或内存认证；不认证实体安卓或Word分页。旧缓存不重新贴上新核查标记。'}
    public={'model':'deepseek-flash','effort':'high','network_search':False,'groups':groups,
            'native':live,'total_real_requests':total_requests,'total_tokens':tokens,
            'manual':manual,'scope_receipts':[r['repair_scope'] for r in scoped]}
    (OUT/'公开实验记录.json').write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
    labels={1:'初轮：长要求＋原始范围',2:'补全对照解析：长要求',3:'最终：仅补原始范围'}
    domains={'physics':'物理','math':'数学','social':'社会科学'}
    rows=''.join('<tr><td>'+str(group['round'])+'</td><td>'+esc(domains[trial['case']])+'</td><td>'+esc('原方案' if trial['variant']=='baseline' else labels[group['round']])+'</td><td>'+esc('通过' if trial['passed'] else '提出问题：第'+ '、'.join(str(i+1) for i in trial['issue_indices'])+'题')+'</td></tr>' for group in groups for trial in group['trials'])
    notes=''.join('<li>'+esc(manual[key])+'</li>' for key in ('initial_pairs','refined_pair','minimal_pair'))
    timing=''.join(f'<tr><td>{esc(stage)}</td><td>{call["seconds"]:.3f} 秒</td><td>{call["usage"]["total_tokens"]}</td></tr>' for stage,call in zip(('设计','独立解题','解析核查','成品核查'),live['calls']))
    checks=''.join('<li>'+esc(text)+'</li>' for text in ui['checks'])
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>再练题原始范围与前置核对验收</title>
<style>:root{{color-scheme:light;--ink:#203c34;--muted:#4d635c}}*{{box-sizing:border-box}}body{{margin:0;background:#eeeae2;color:var(--ink);font:16px/1.8 "Microsoft YaHei",sans-serif}}main{{max-width:1100px;margin:auto;padding:34px 22px 70px}}header,section{{background:#fffdf8;border:1px solid #d9ded6;border-radius:20px;padding:26px 30px;margin-bottom:20px}}h1{{font-size:32px;line-height:1.35}}h2{{font-size:23px}}.tag{{color:#57746a;letter-spacing:.12em;font-size:13px}}.notice,blockquote{{padding:18px 20px;border-radius:12px;background:#fff1d8;border-left:4px solid #b9842c;margin:18px 0}}.good{{padding:18px 20px;border-radius:12px;background:#eaf3ed}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{border-bottom:1px solid #dce2db;text-align:left;padding:10px 12px;vertical-align:top}}a{{color:#196b58;text-underline-offset:3px}}li{{margin:8px 0}}.muted{{color:var(--muted)}}@media(max-width:600px){{main{{padding:18px 10px}}header,section{{padding:20px 16px}}h1{{font-size:25px}}table{{font-size:12px}}th,td{{padding:7px 5px}}}}</style>
<main><header><div class="tag">STUDYFORGE · 2026-10-22 · SOURCE ACCEPTANCE</div><h1>再练题：把原卡点交给审查，避免只看设计者自述</h1><p>完成一项可验证的信息传递修复，并保留不支持提示词扩写的实验结果。源码更新，未打包EXE。</p><p>{link(ROOT/'验收最新版.vbs','打开最新版源码应用')} · {link(word,'下载最终实跑单题DOCX · 无答案')} · {link(OUT/'公开实验记录.json','公开实验与计量记录')}</p><p class="muted">验收应用前，先在Windows托盘彻底退出旧StudyForge，再双击源码启动入口；关闭窗口会继续后台运行。</p></header>
<section><h2>这次真正修复了什么</h2><p>设计时已收到原失分题和补讲；原审查请求只收到新题、参考解及设计者的repair_focus，没有收到原卡点依据。现在两项核查和需要时的修订都收到所选原题、暂定错因、补讲节选和核对办法。</p><div class="good">{esc(manual['accepted'])}</div><ul><li>只传所选目标，不扩大到未选失分项或其他对话。</li><li>原资料与旧补讲保持区分，自报不提升为确定能力结论；节选标记保留。</li><li>独立解题仍只收到新题与原资料，不收到设计参考解、错因或旧补讲。</li><li>私有核查记录保存实际范围指纹与目标号；学生题单和Word不含参考答案、错因设计说明。</li><li>新范围数据只用于新任务，已有缓存不被补写成经过了新检查。</li></ul></section>
<section><h2>更长的提示词没有胜出</h2><div class="notice">{esc(manual['rejected'])}</div><p>同一DeepSeek Flash、high设置，关闭联网，使用合成物理／数学／社会科学题组。交错安排新旧顺序，每组使用固定相同的候选题与参考说明；不是盲测学生的能力。公开结果只保留判定与计量，不披露尚未提交练习的私有答案。</p><table><thead><tr><th>轮次</th><th>领域</th><th>条件</th><th>原样判定摘要</th></tr></thead><tbody>{rows}</tbody></table><ul>{notes}</ul><p>完整请求与回答保留在本机私有审计文件中，本页未链接其中的参考答案。最终实现仅保留必要的原始范围数据。</p></section>
<section><h2>最终源码真实跑出的再练题</h2><blockquote>{esc(worksheet['questions'][0]['question'])}</blockquote><p>{esc(manual['native'])}</p><p>{link(word,'下载本题DOCX（提交前无答案）')} · {link(LIVE/'student-worksheet.json','公开题单记录')}</p><table><thead><tr><th>步骤</th><th>响应时间</th><th>总Token（含推理）</th></tr></thead><tbody>{timing}</tbody></table><p>最终流程{live['seconds']:.3f}秒，4次真实请求，沿用设计、独立求解与两项核查。此前另一小样例66.493秒，不能据本次声称提速。全部本轮实验累计{total_requests}次真实请求、{tokens}总Token；这些是研发实验费用，不是每份练习固定调用次数。</p></section>
<section><h2>验证与边界</h2><p>最终{gate['tests']['total']}项关联回归通过，失败、错误、跳过均为0；两个生产文件指纹在测试前后相同并与本页生成时一致。针对性回归先复现2处范围缺失；最终11项范围测试包含原生生成／修订／再求解／Word防泄漏。</p><p>实际电脑及配对HTTPS手机通过{len(ui['checks'])}项操作，使用12项模拟请求、0次新云请求：</p><ol>{checks}</ol><p>{link(GATE/'command.json','最终测试命令、计数与源码指纹')} · {link(GATE/'regression.xml','最终回归XML')} · {link(UI/'ui-report.json','实际两端操作记录')}</p><div class="notice">{esc(manual['limits'])}</div><p>扩写提示期间的一次180项回归本身全通过，但运行中因最终撤下长要求导致源码指纹变化，已作废为最终验收依据；上述是重新冻结最终源码后完成的独立一轮。本轮没有修改通用导师人设、学习画像分数或并发上限。</p></section></main></html>'''
    page=page.replace('2026-10-22 · SOURCE ACCEPTANCE','2026-10-23 · SOURCE ACCEPTANCE')
    target=OUT/'再练题原始范围与前置核对验收.html';target.write_text(page,encoding='utf-8')
    class Links(HTMLParser):
        def handle_starttag(self,tag,attrs):
            for key,value in attrs:
                if key not in ('src','href') or not value:continue
                parts=urlsplit(value);assert not parts.scheme and not parts.netloc
                assert (OUT/unquote(parts.path)).resolve().is_file(),value
    Links().feed(page)
    (OUT/'manifest.json').write_text(json.dumps({'gate':gate,'ui':ui,'native':live,'real_requests':total_requests,
        'public_files':{str(p.relative_to(ROOT)):sha(p) for p in (word,LIVE/'student-worksheet.json',target,OUT/'公开实验记录.json')}},ensure_ascii=False,indent=2),encoding='utf-8')
    doc=ROOT/'docs/再练题原始范围与前置核对验收.md'
    doc.write_text(f'''# 再练题原始范围与前置核对验收

2026-10-23，源码更新，未打包。实验目录沿用本轮开始时的20261022标记。

## 实施

- 补上原缺失的所选原题、暂定错因、已交付补讲节选与检查办法，供两项核查及必要时修订。独立解题仍只看新题和资料。
- 私有记录保存范围版本2、指纹和原目标号，表示实际提供的数据，不是正确性认证。公共JSON和DOCX不泄漏参考解或设计说明；旧缓存不冒贴新标记。
- 不增加固定模型轮次、不改通用教师规则、不新增画像或评分。

## 真实实验与取舍

共{total_requests}次真实Flash/high请求。10次核查对照覆盖物理、数学与社会科学；扩写的前置检查要求没有稳定优势，且存在误拦风险，已撤下。最终采用仅补原始范围数据的方式，物理对照新旧都放行，也仍未指出原点电荷样例的条件／前置问题。完整原始请求与回答保留在私有实验文件，公开页不披露未提交题目的私有参考答案。

两次原生单题实跑各4次请求；最终源码{live['seconds']:.3f}秒，完整导出1题DOCX，未额外生成另一处失分项。人工核对确认情境贴合原资料已有的外部电荷说明；“盒子”改称假想曲面会更清楚，原样保留。不能作为普遍提速或全面教学质量证据。

## 验证

- 最终{gate['tests']['total']}项关联回归全通过，两个生产文件指纹前后相同；含11项新针对性测试。首轮针对性先复现2处缺失。
- 实际电脑／配对HTTPS手机{len(ui['checks'])}项操作通过，12项模拟请求检查私有范围传递、所选目标、缓存复用、Word下载与原评分／画像不变。
- 扩写提示期间的180项回归虽通过，但因源码在运行中变更导致指纹检查不通过，仅作过程记录，最终已重新验收。
- 不认证实体安卓、Word分页、全软件速度或内存；源码未打包，手机壳及业务UI保持v68。

可打开验收页：[{target.name}]({target.as_posix()})
''',encoding='utf-8')
    print(str(target),flush=True)


if __name__=='__main__':main()
