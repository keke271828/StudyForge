"""Offline acceptance: rejected prompt, real tool responses, controlled delivery."""
import base64
import hashlib
from html import escape as esc
import json
from pathlib import Path
import re
import shutil
from xml.etree import ElementTree

from scripts.build_teaching_comparison import TEMPLATE,inline_script

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/math-teaching-acceptance-20261016'
PROMPT=ROOT/'build/teaching-construction-eval-20261015-1'
AGENTS=[ROOT/'build/math-agent-real-20261015-1',ROOT/'build/math-agent-boundaries-20261015-1']
FLOW=ROOT/'build/math-generation-workflow-20261015-3'
UI=ROOT/'build/math-tools-ui-20261016-1'
TITLES={'limit':'极限唯一性：为什么取一半与最大门槛','cauchy_followup':'柯西不等式：为什么固定 t=1 不够',
        'gauss':'高斯定律：净通量与各点电场','social':'大样本、显著与因果'}
NOTES={
    'limit':{
        'baseline':'现有版给出实际数列 xₙ=1+1/n 的计算和统一门槛，来源位置较完整。主线基本连贯，证明与总结仍有重复。',
        'candidate':'关键构造基本正确，但换成假设门槛的示意，不如实际数列的完整演算；来源位置更弱。不能因这次更快就认定讲解更好。'},
    'cauchy_followup':{
        'baseline':'回答了单点非负只给弱约束、任意 t 非负给更强约束的缺口。假设 A、B、C 数值用来比较逻辑约束，并明确不代表真实向量。',
        'candidate':'有明确错误：“当 B>0 时，a 与 b 同向”。正点积不足以推出同向。这份失败样例原样保留，候选未加入软件。'},
    'gauss':{
        'baseline':'以均匀场与立方体算出两面通量 +12、−12，其余为零，解释净量与局部量。单位交代不足，“数字单位不重要”的说法教学上欠妥。',
        'candidate':'基本反例和计算清楚，初始电场与边长有单位，但后续通量单位不完整。看不出稳定胜过现有版的证据。'},
    'social':{
        'baseline':'假设例子有标注，主要的混杂、反向因果和显著／效应大小区分清楚。但大样本下重复调查会怎样的表述偏强，未充分交代抽样和模型条件。',
        'candidate':'共同因素的具体情景有帮助；统计显著相关“不是随机波动”的表述过于绝对，对证据条件的清单也可能让读者误以为必须全部具备。仍需谨慎读。'},
}
AGENT_NOTES={
    (0,'tutor'):'工具实际返回点积1、Gram差1、不同向、约45°，两组分数也算对；回答能区分反例与一般证明。但开头把正点积一概叫锐角，漏掉0°；正文也偏长。不能称整篇完全通过。随后增加并测试了0°、180°与零向量的本机分类和返回提示。',
    (0,'lecture'):'确实调用两次工具，具体算式与方向判定正确；正文给出了 [0°,90°) 却在开头和总结又一概称锐角，前后不严谨。保留原回答，不把工具成功包装成文档质量全部合格。',
    (1,'tutor'):'修正工具边界返回后，正确核算同向0°、反向180°、零向量夹角未定义。区分了几何夹角与按点积定义的代数正交；教材用语仍应按原文约定。范围补讲有帮助，篇幅和术语密度仍可改进。',
    (1,'lecture'):'边界数值和主要结论正确，区分了零向量的正交约定与夹角。不过把两个半开区间统称为“闭区间”、从柯西界限直接转到余弦取遍的衔接，以及“否证反例”的措辞都不够严谨；并非可直接当定稿教材的满分样本。',
}


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def copy(source,name):
    target=OUT/name;target.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(source,target)
    return target.relative_to(OUT).as_posix()


def main():
    OUT.mkdir(exist_ok=True,parents=True)
    results=load(PROMPT/'results.json');inputs=load(PROMPT/'inputs.json');groups=[];times=[]
    assert len(results)==8 and all(r['status']=='completed' and r['model_requests']==1 for r in results)
    for case in inputs:
        pair={r['arm']:r for r in results if r['case']==case['id']};rows=[]
        for arm,label in [('baseline','现有教学规则'),('candidate','未采用的候选规则')]:
            row=pair[arm];source=PROMPT/row['answer_file'];text=source.read_text(encoding='utf-8')
            request=load(PROMPT/(case['id']+'-'+arm+'-records.json'))
            rows.append({'case':case['id'],'arm':arm,'label':label,'text':text,'review':NOTES[case['id']][arm],
                'seconds':round(row['seconds'],2),'output_chars':len(text),'input_chars':sum(t['input_characters'] for t in row['http_attempts']),
                'response_model':'deepseek-flash','usage':[t['usage'] for t in row['http_attempts']],
                'sha256':sha(source),'request':request})
            copy(source,'原样输出/'+source.name)
        times.append('<tr><td>'+esc(TITLES[case['id']])+'</td>'+''.join('<td>'+str(round(pair[a]['seconds'],2))+' 秒</td>' for a in ('baseline','candidate'))+'</tr>')
        groups.append({'round':'同资料首次回答对照','case':case['id'],'title':TITLES[case['id']],
            'question':case['question'],'source':case['source'],'rows':rows})
    agent_times=[]
    for index,folder in enumerate(AGENTS):
        packets=load(folder/'results.json');rows=[]
        assert len(packets)==2 and all(r['status']=='completed' and r['model_requests']==2 for r in packets)
        for row in packets:
            role=row['role'];source=folder/row['answer_file'];text=source.read_text(encoding='utf-8')
            request=load(folder/(role+'-public-wire.json'))
            assert not any('reasoning_content' in m for p in request for m in p['messages'])
            label=('AI导师' if role=='tutor' else '文档讲解AI')+(' · 初接入' if index==0 else ' · 退化与端点检查')
            rows.append({'case':'math'+str(index),'arm':role,'label':label,'text':text,'review':AGENT_NOTES[index,role],
                'seconds':round(row['seconds'],2),'output_chars':len(text),'input_chars':sum(t['input_characters'] for t in row['http_attempts']),
                'response_model':'deepseek-flash','usage':[t['usage'] for t in row['http_attempts']],
                'sha256':sha(source),'request':request})
            copy(source,'原样输出/math'+str(index)+'-'+role+'.md')
            agent_times.append('<tr><td>'+esc(label)+'</td><td>'+str(round(row['seconds'],2))+' 秒</td><td>2</td><td>'+str(len(row['tool_events']))+'</td></tr>')
        groups.append({'round':'真实Agent工具调用','case':'math'+str(index),'title':'数值反例与精确分数' if index==0 else '同向0°、反向180°与零向量',
            'question':packets[0]['question'],'source':'导师本次仅收到题目与共同教学规则；文档路径另有短原资料：\n本资料讨论非零实向量。点积为各对应分量乘积的和，同向要求一个向量是另一个的正倍数。\n\n两种角色并非完全相同输入的质量排名。工具使用由问题明确要求。',
            'rows':rows})
    workflow=load(FLOW/'results.json');ui=load(UI/'ui-results.json')
    assert workflow['passed'] and workflow['controlled_model_requests']==3 and not workflow['external_model_requests']
    assert ui['passed'] and len(ui['checks'])==4 and ui['controlled_model_requests']==4 and not ui['external_model_requests']
    tree=ElementTree.parse(ROOT/'build/math-checks-acceptance-20261016.xml').getroot()
    tests=tree.findall('.//testcase');assert len(tests)>=139 and not any(t.find(tag) is not None for t in tests for tag in ('failure','error','skipped'))
    copy(FLOW/workflow['docx_file'],workflow['docx_file'])
    for name in ['电脑端数学核验.png','手机端数学核验.png']:copy(UI/name,name)
    for filename in ['studyforge/math_checks.py','studyforge/agent_tools.py','scripts/teaching_construction_candidate.py',
                     'scripts/check_math_generation.py','tests/test_math_checks.py']:
        copy(ROOT/filename,'代码快照/'+Path(filename).name)
    intro='''<header><div class="eyebrow">STUDYFORGE · TEACHING ACCEPTANCE · 2026-10-16</div>
<h1>首次讲解与数学核验：真实回答、失败样例和可用改进</h1>
<p>12份原样回答：4组教学规则对照，以及导师／文档AI的4次工具调用实验。<a href="../../验收最新版.vbs">打开当前源码版验收</a> · <a href="../../web/help/guide.html#permissions">查看软件内指南</a>。本轮未打包。</p>
<div class="notice"><strong>实施结论：</strong>候选教学提示未采用，因其没有稳定改善，并出现“正点积意味着同向”的明确错误。软件已增加按需本机数学核验，支持精确有理数与实有理向量；没有增加固定审查轮次。工具结果可能被AI误述，有限数例也不证明一般定理。下方保留了实际回答中的不足。</div></header>'''
    status='''<section class="prompt"><h2>已可验收的改动</h2>
<p>在学习工作台开启AI工具后，可以要求导师批量核验算式或向量；只读模式也能使用。无须安装数学软件、读取文件或联网。本机核算在工作线程执行，有批量、长度、维度和计算大小限制。不能执行输入中的函数或程序。</p>
<p>0.1+0.2 精确返回3/10；(1,0)与(1,1)点积为1但不同向；同向与反向分别识别为0°、180°，零向量夹角未定义。向量角度标为近似值，方向由精确算术判定。符号变量、函数、无理数等不支持，不会静默近似。</p>
<p>导师、讲解与私有作业流程共享工具注册；关闭总工具开关时不可用。私有作业的核验输入、数字结果和输入校验细节不写入公开工具活动。未提交答案仍按原有流程保护；本轮没有新增作答成绩。</p>
<p><strong>开销：</strong>不使用工具时没有这项额外模型请求；使用后需要模型续答。批量算术一次最多16项，工具本身不调用另一模型。没有证明长视频、扫描PDF或整体教学任务已普遍提速。</p></section>
<section class="prompt"><h2>首次讲解规则对照</h2><p>DeepSeek Flash，服务实际返回 deepseek-flash，high。每个方案一次、同资料和同本次要求，仅替换共同证明讲解规则；数学选直观与专业并存，社会科学选通俗清晰，均为精学。关闭工具和联网，不测试OCR、视频或Word导出。三题使用实际文档提示构造，一题为导师追问组件；不等于完整桌面任务。不是网页端对照，也未进行盲评或多次重复。</p>
<div class="report-table"><table><thead><tr><th>题目</th><th>现有规则</th><th>候选规则</th></tr></thead><tbody>'''+''.join(times)+'''</tbody></table></div><p>耗时包含本次调用与本机调度，受服务、缓存、推理和回答长度影响。不能以单次更短证明质量更高或长期更快。四组都未提供习题要求，没有因此自动发布习题。</p></section>
<section class="prompt"><h2>真实数学工具调用</h2><p>导师使用现有原生Agent调用；文档使用实际讲解函数和Agent工具循环。以下短例均由问题明确要求使用工具，未测试默认自动调用覆盖率。不是完整扫描书或视频讲解。前两份在端点提示完善前完成，后两份专门检查0°、180°与零向量，均未改写原输出。</p>
<div class="report-table"><table><thead><tr><th>路径</th><th>耗时</th><th>模型请求数</th><th>本机工具次数</th></tr></thead><tbody>'''+''.join(agent_times)+'''</tbody></table></div><p>具体核算均成功，边界探测的主要数值结论正确。首轮仍漏说0°端点；边界文档仍有“闭区间”等措辞错误。这说明工具可提高数值可查性，不能保证生成文本的所有细节都正确。</p></section>
<section class="prompt"><h2>完整导出与界面验收</h2>
<ul><li>__TEST_COUNT__项最终去重程序检查通过，含精确算术、输入约束、大数方向、近似角舍入提示、原生工具往返、只读与审批权限、对话和画像隔离、私有作业及既有模型调用。初次有1项私有错误提示遮住总工具关闭原因，修正后通过。</li>
<li>受控完整流程：重新读原文件而非预览，原生模型工具往返2次＋快速核查1次，实际写出单独的所选Word文件，没有习题或掌握分数。此流程用受控响应、0次外部模型请求；验证文件容器与正文，未用Microsoft Word做视觉验收。</li>
<li>实际Electron电脑页面与已配对HTTPS手机页面4项交互检查通过：执行时中文数学工具状态、最终回答刷新恢复、手机原生工具调用、公开事件不含数值答案且不新增题单或成绩。共4次受控模型请求，0次外部请求。首个界面脚本错把临时进度当成永久历史；改为分别验证执行进度和保存的回答后通过。</li></ul>
<p><a href="数学核验与Word导出流程样例.docx">下载受控流程Word样例</a> · <a href="电脑端数学核验.png">电脑界面截图</a> · <a href="手机端数学核验.png">手机界面截图</a></p>
<p>这轮实际外部模型请求共16次：规则对照8次＋4份工具回答各2次。受控流程与回归不计入真实模型质量样本。</p></section>
<section class="prompt"><h2>打开软件验收</h2><p><a href="../../验收最新版.vbs">双击“验收最新版.vbs”打开当前源码版</a>。本轮未打包；已经在运行的旧源码窗口需要完全退出后重新打开。选择现有模型与推理强度，在设置中开启AI工具即可，只读权限可用。</p>
<p>可发送：“请用数学核验工具检查0.1+0.2和1/3+1/6，再核验向量(1,0)与(1,1)是否同向。解释数例能说明什么，不出题。”也可在生成讲解的本次要求中加入核验要求，沿用所选审查强度。</p>
<p><a href="../../web/help/guide.html#permissions">软件内使用指南</a>已同步数学核验的用法和范围。符号证明、一般定理、来源可靠性及社会科学因果条件仍需适当依据；不以加算术工具替代教学解释。</p></section>'''
    css=(ROOT/'web/vendor/katex.css').read_text(encoding='utf-8')
    css=re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((ROOT/'web/vendor/fonts'/m[1]).read_bytes()).decode()+')',css)
    css=re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
    data={'groups':groups,'count':sum(len(g['rows']) for g in groups),'failures':[]}
    page=re.sub(r'<header>.*?</header>',lambda _:intro,TEMPLATE,flags=re.S)
    page=page.replace('<main>','<main><details class="prompt" id="acceptanceInfo"><summary>实施结果、计时与验收证据（展开查看）</summary>'+status+'</details>',1).replace('<title>StudyForge · 讲解质量真实对照</title>','<title>首次讲解与数学核验实际对照 · StudyForge</title>')
    page=page.replace('grid-template-columns:repeat(3,minmax(0,1fr))','grid-template-columns:repeat(2,minmax(0,1fr))')
    page=page.replace('</style>','.report-table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d8e2df;padding:10px;text-align:left}th{background:#eef5f1}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}pre{word-break:break-word}</style>',1)
    page=page.replace('本次提供的完整合成原资料','本组原资料与输入说明').replace('提示 \'','各请求输入共 \'')
    page=page.replace('核对实际请求、用量与原文指纹','核对公开消息、实际用量与回答指纹')
    page=page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。',
        '全部回答、渲染器与字体已嵌入此页。阅读和切换不发送模型请求。外部文件链接需保留在原目录；有缺陷的原样回答仅供验收，不是定稿教材。')
    page=page.replace('__TEST_COUNT__',str(len(tests))).replace('__KATEX_CSS__',css).replace('__PAYLOAD__',json.dumps(data,ensure_ascii=False).replace('<','\\u003c'))
    libraries='\n'.join(inline_script((ROOT/'web/vendor'/n).read_text(encoding='utf-8')) for n in ['marked.js','purify.js','katex.js'])
    page=page.replace('__LIBRARIES__',libraries).replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    target=OUT/'首次讲解与数学核验实际对照.html';target.write_text(page,encoding='utf-8')
    manifest={'date':'2026-10-16','answers':data['count'],'groups':len(groups),'real_model_requests':16,'program_checks':len(tests),
        'controlled_workflow':workflow,'ui':ui,'candidate_deployed':False,'package_created':False,
        'files':{str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='manifest.json' and 'electron' not in str(p)}}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(target),'answers':data['count'],'real_model_requests':16,'program_checks':len(tests)},ensure_ascii=True))


if __name__=='__main__':main()
