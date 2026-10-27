"""Acceptance report: input roles, retained cautions and bounded real evidence."""
import hashlib
from html import escape as esc
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/review-data-acceptance-20261015'
PROBE=ROOT/'build/review-data-boundary-20261015-1'
WORKFLOW=ROOT/'build/review-data-workflow-20261015-1'
TITLES={'delivered_high':'数学长讲解','weak_wrong':'闭区间被误写成严格条件',
        'strong_correct':'仍保留严格条件的正确讲解','correct_social_control':'社会科学来源边界对照'}
MANUAL={
 'delivered_high':'两种输入都反对既有核查／来源提示，并质疑“假装门槛为100”的演示。演示是否误导取决于其用途，不直接把该意见计作已确认错误；使用一般N₂的改写更完整。两臂仍未可靠指出“别无选择”、等半径必合并边界和半径不等便不能以中点分隔等过强断言。结构分隔没有解决这些漏检。软件提示本身有明确作用，不能仅按模型意见清除；后续程序保护保留它们。',
 'weak_wrong':'两臂都指出：仅给闭区间包含，不能推出严格内点；并提出相应的正文／总结修正。',
 'strong_correct':'两臂都通过：本段明确保留严格前提，提到一个较弱的闭区间包含关系不会撤销它。',
 'correct_social_control':'原先标为正确对照。分开输入版质疑“问卷里没有测量的机制”这句，因来源仅写调查、没有指明问卷或测量状况，并提出条件化改写。该措辞可理解为一般条件，也可能让读者误以为已知研究设计；人工保留这一来源边界／表达争议，不能据此简单计为明确误报或质量提升。原标签未改写。',
}


def load(p):return json.loads(p.read_text(encoding='utf-8'))
def detail(title,text):return '<details><summary>'+esc(title)+'</summary><pre>'+esc(text)+'</pre></details>'


def main():
    OUT.mkdir(exist_ok=True);(OUT/'原样输出').mkdir(exist_ok=True)
    rows=load(PROBE/'results.json');inputs=load(PROBE/'inputs.json');work=load(WORKFLOW/'results.json')
    assert len(rows)==8 and all(r['status']=='completed' and r['model_requests']==1 for r in rows)
    assert len(work)==2 and all(r['passed'] and not r['external_model_requests'] for r in work)
    tests={}
    files=['review-input-final-regression-v3-20261015.xml','review-input-integration-20261015.xml']
    for file in files:
        for c in ET.parse(ROOT/'build'/file).getroot().findall('.//testcase'):tests[c.get('classname'),c.get('name')]=c
    assert tests and not any(c.find(tag) is not None for c in tests.values() for tag in ('failure','error','skipped'))
    summary=[];cases=[]
    for case in inputs:
        pair={r['arm']:r for r in rows if r['case']==case['id']};cells=[]
        summary.append('<tr><td>'+TITLES[case['id']]+'</td>'+''.join('<td>'+('提出问题' if r['reports'][0]['issues'] else '判通过')+
            '<br>'+f"{r['seconds']:.2f} 秒 / {r['model_requests']} 次"+'</td>' for r in (pair['baseline'],pair['separated']))+'</tr>')
        for arm,label in [('baseline','原输入'),('separated','分开输入')]:
            row=pair[arm];final=PROBE/(case['id']+'-'+arm+'-final.md');target=OUT/'原样输出'/(TITLES[case['id']]+'－'+label+'.md')
            shutil.copyfile(final,target)
            records=load(PROBE/(case['id']+'-'+arm+'-records.json'))
            cells.append('<div><h4>'+label+'</h4><a href="原样输出/'+esc(target.name)+'">打开讲解原样输出</a>'+detail('查看最终审核回答',records[-1]['response'])+'</div>')
        cases.append('<article><h3>'+TITLES[case['id']]+'</h3><p class="note">'+MANUAL[case['id']]+'</p>'+
            detail('查看本例资料、要求与原讲解','资料：\n'+case['source']+'\n\n要求：\n'+case['requirements']+'\n\n原讲解：\n'+case['document'])+
            '<div class="pair">'+''.join(cells)+'</div></article>')
    workflow_rows=[]
    for row in work:
        target=OUT/row['docx_file'];shutil.copyfile(WORKFLOW/row['docx_file'],target)
        workflow_rows.append('<tr><td>'+('平衡' if row['mode']=='balanced' else '严谨')+'</td><td>'+str(row['controlled_model_requests'])+
            ' 次受控请求</td><td>原文完整；修订和复核保留旧疑点；Word已检查</td><td><a href="'+esc(target.name)+'">受控流程 Word 样例</a></td></tr>')
    css=re.search(r'<style>(.*?)</style>',(ROOT/'build/content-check-review-20261015/内容核对与审核候选实际对照.html').read_text(encoding='utf-8'),re.S)[1]
    intro=f'''<header><span class="kicker">STUDYFORGE · 学习质量验收 · 2026-10-15</span><h1>审核资料分开提供，修订保留核查记录</h1><p>本轮修复审核输入混杂和核查记录可被模型改写清除的问题。8次真实组件请求仍显示长文漏检；程序修复不等同于模型判断已可靠。</p><div class="grid"><div class="metric"><strong>{len(tests)} 项</strong>去重程序回归通过</div><div class="metric"><strong>8 次</strong>实际 DeepSeek 审核请求</div><div class="metric"><strong>2 份</strong>完整受控生成与 Word 交付</div><div class="metric"><strong>原有次数</strong>极速、快速、平衡、严谨调用次数保持</div></div></header>'''
    features='''<section><h2>已进入源码的修改</h2><ol><li>完整资料、待审讲解、本机代数线索和先前审核意见使用独立数据字段；任务要求放在数据之外。资料中的同名标签、JSON、换行或公式仍作为原内容保留。</li><li>审核与修订保存来源／讲解的字符数和指纹，不把完整聊天或资料再复制进记录。分开输入不是正确性认证，也不是绝对的指令注入防护。</li><li>普通局部修正保护已有“来源定位需核对”“待核实事项”“核查说明”等记录；同一问题的一组修正若碰到受保护段落，整组不自动应用，其他合法修正继续。</li><li>平衡与严谨模式整篇改写时，漏掉的原记录恢复到总结之前；同一唯一提示被改写成“已完全核实”时恢复原记录。仅存在于代码块的旧提示不能冒充可见记录，多部分的重复记录也按出现次数保留。</li><li>保留已有模式、模型、推理强度、原文范围和请求次数，不新增自动审核。保留疑点不代表认定旧疑点必定成立；实际解决状态需要再核对。</li></ol><p class="note">这是修订可靠性的改进。长文过强断言、构造动机的解释质量、审核误判仍需要继续评估。它不会因为读过或审过，就把内容计为学生已经掌握。</p></section>'''
    real='''<section><span class="kicker">原始结果保留</span><h2>8次真实审核：结果与局限</h2><p>4例×原输入／分开输入各1次，使用 deepseek-flash、high，完整资料与同一待审讲解。每对最多2个名额重叠，配对依次进行。只测审核组件，未运行完整Agent工具、联网、学习画像或整本扫描书；保存最终回答、用量和计时，不保存模型思考文本。</p><p>以下请求测试输入分隔版本。后来补上的核查记录保留是程序行为，由下方受控完整流程和专门边界测试核验，未宣称已由这8次模型请求验证。时间受服务波动与共享并发影响，不做总体速度排名。</p><div class="table-wrap"><table><thead><tr><th>样例</th><th>原输入</th><th>分开输入</th></tr></thead><tbody>'''+''.join(summary)+'</tbody></table></div>'+''.join(cases)+'</section>'
    workflow='''<section><h2>完整受控生成：修订记录确实进入 Word</h2><p>使用实际任务、原文件重读、审核、修订、总结与导出路径；模型响应由测试控制，外部模型请求为0。初稿有错误与一条旧来源提示，修订回应修正正文并故意漏掉提示，程序恢复该提示；严谨复核确实接收恢复后的文档。Word内没有审核数据字段或旧错误正文；学习分数和习题没有增加。</p><div class="table-wrap"><table><thead><tr><th>模式</th><th>完整流程调用</th><th>结果</th><th>打开样例</th></tr></thead><tbody>'''+''.join(workflow_rows)+'''</tbody></table></div><p class="note warn">这两份是受控流程样例，用来检查程序和导出，不是真实模型教学成品，不用于评价AI智力。这里没有重新做安卓实机、全软件内存或长视频速度验收。</p></section>'''
    open_section='''<section><h2>打开验收</h2><p>关闭正在运行的旧StudyForge，再双击<a href="../../验收最新版.vbs">验收最新版.vbs</a>使用当前源码。本轮未重新打包。</p><p>沿用原来的生成选项即可。生成后可查看文档中的来源／未核实提示和末尾总结；怀疑某条提示或正文时，使用上一轮新增的“讲解可能有误或依据不清，请先核对”入口定位原句。</p><p>操作说明已同步到<a href="../../web/help/guide.html#feedback">软件内使用指南</a>。历史提示的保留不直接给出最终正确性判断，避免把删掉提示误当成完成验证。</p></section>'''
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>审核资料分开提供与核查记录保留 · StudyForge</title><style>'+css+'</style><main>'+intro+features+real+workflow+open_section+'</main></html>'
    target=OUT/'审核输入与核查记录保留实际对照.html';target.write_text(page,encoding='utf-8')
    counts={'regression_tests':len(tests),'live_requests':8,'controlled_workflows':2,'controlled_model_requests':11,
        'case_rows':4,'regression_xml':files,'packaged':False,
        'source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
            ('studyforge/review.py','studyforge/review_input.py','studyforge/review_corrections.py','studyforge/lesson_cautions.py')}}
    (OUT/'验收摘要.json').write_text(json.dumps(counts,ensure_ascii=False,indent=2),encoding='utf-8')
    doc=f'''# 审核输入分隔与修订核查记录保留验收

2026-10-15，源码完成，本轮未打包。

## 实施

完整资料、讲解、有限本机代数线索与已有审核意见分别放入审核数据字段，任务要求放在数据之外；快速核查、平衡修订、严谨初审／修订／复核使用同一分隔方式。保留每个字符、公式和来源位置；记录字符数与指纹，不重复保存原文到审查小记录。旧报告仍可读取，无数据库迁移。

局部修正保护此前可见的来源／未核实／核查状态段落，涉及受保护段落的整组修改不自动应用。整篇改写遗漏的旧记录恢复到总结之前；同一唯一提示被模型改成“已完全核实”时恢复原记录。代码块／引用中的标题不冒充软件提示，重复记录按出现次数保留，重复处理不新增副本。保留的是待核对的历史限制，不把它说成已证错误，也不能视为确认问题仍未解决。

没有新增模型步骤，没有改变极速0次、快速1次、平衡1次及必要时修订、严谨3次及必要时修订与3次复核的机制。学生的模型、推理强度、资料范围、学习模式与画像规则保持。本次没有重新判断所有历史教学需求已满足。

## 验收

- {len(tests)}项最终去重程序检查通过：审核数据／修订记录、范围、局部修正、来源保护、本机算术、总结、生成恢复、同一导师上下文、并行审核、原文件读取、任务控制／进度、DeepSeek独立运行及书库来源交付。前面138与144项运行均与最后一组重叠，不累计。
- 2个真实完整程序路径，响应受控、0次外部模型请求：平衡3次、严谨8次组件请求，包含首讲；故意省掉旧提示的修订回应被恢复，严谨复核接收该记录，实际DOCX内保留提示与正确正文，未含数据包装字段。没有新增分数或题单。
- 8次真实DeepSeek Flash high组件审核，4例成对、每臂1次；完整输入和最终回答保存，不保存模型思考文本。长文两臂仍漏检过强断言，并对演示和软件提示提出争议意见。闭区间错误两臂均发现，严格前提对照均通过；社会科学对照的“问卷”措辞被新版提出来源不足异议，人工保留条件性解释／资料设计暗示的争议，不据此计算准确率。
- 实际审核请求验证输入分隔版本，后补的记录保留由专门边界测试及完整受控流程验证。实际时长不能据单次成对样本证明普遍提速，输入分隔也不能保证模型正确或完全防注入。
- 本轮无界面布局改动；指南补充说明。未另作安卓实机、总RAM、长视频或长期学习效果测试。

## 打开

关闭旧实例，双击工作区 `验收最新版.vbs`。沿用现有选项生成讲解即可；怀疑正文或核查提示时，可在原反馈中定位并主动请导师核对。

[实际对照报告](../build/review-data-acceptance-20261015/审核输入与核查记录保留实际对照.html)包含8份最终审核回答与原样输出、两份受控DOCX。原始真实试验在`build/review-data-boundary-20261015-1`；完整流程在`build/review-data-workflow-20261015-1`；最终程序检查为{', '.join('`build/'+f+'`' for f in files)}。
'''
    (ROOT/'docs/审核输入分隔与核查记录保留验收.md').write_text(doc,encoding='utf-8')
    status=ROOT/'docs/当前功能状态与待验收清单.md';text=status.read_text(encoding='utf-8');marker='## 已有实现及验收记录\n\n'
    entry=f'2026-10-15 完成 [审核输入分隔与核查记录保留](审核输入分隔与核查记录保留验收.md)：审核／修订分别提供完整资料、待审讲解、本机线索与先前意见；局部替换保护核查提示，整篇改写遗漏或自行改为已核实时恢复旧记录，保留重复次数与总结位置。{len(tests)}项去重回归、2个受控完整生成与实际Word交付通过；8次真实审核对照仍有长文漏检与来源措辞争议，不宣称准确率或速度总体提高。原请求次数、模型与推理强度保持，指南同步，源码未打包。\n\n'
    if '2026-10-15 完成 [审核输入分隔与核查记录保留]' not in text:
        assert marker in text;status.write_text(text.replace(marker,marker+entry,1),encoding='utf-8')
    else:
        pattern=re.escape('2026-10-15 完成 [审核输入分隔与核查记录保留]')+r'.*?\n\n'
        status.write_text(re.sub(pattern,lambda match:entry,text,count=1),encoding='utf-8')
    print(target)


if __name__=='__main__':main()
