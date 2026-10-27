"""Offline construction comparison, actual symbolic tool answers and fast review."""
import asyncio
import base64
import hashlib
from html import escape as esc
import json
import os
from pathlib import Path
import re
import shutil
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from scripts.build_teaching_comparison import TEMPLATE,inline_script

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/polynomial-teaching-acceptance-20261016'
PROBE=ROOT/'build/construction-relations-real-20261016-1'
AGENT=ROOT/'build/polynomial-agent-real-20261016-1'
AUDIT=ROOT/'build/polynomial-fast-review-real-20261016-1'
UI=ROOT/'build/polynomial-ui-20261016-1'
NOTES={
 'cauchy_parameter':('参数、配方与弱信息对比讲清，假设系数反例未冒充真实向量；但没明确A>0就除A，且“必须跑遍所有实数”的说法过强：本例固定±10的两次非负性也足以给界。',
                     '明确A>0，投影关系有帮助，也保留系数反例身份；仍偏向“必须看整条抛物线”的措辞，A=0未展开。这次更慢，不能宣称构造讲解全面改善。'),
 'limit_radius':('从不交关系推回0<ε≤半间距，符号门槛与假想例子正确；补充三角不等式、再次证明和总结有重复。',
                  '同样正确推回半径条件，且清楚说明大半径只让当前构造失效，不代表双极限序列存在；但3855字符明显更长，虽本次较快也未必更高效。'),
 'integrating_factor':('由乘积法则匹配μ′=pμ，合法非零因子、示例通解和代回均正确，解释已经很完整。',
                       '目标、系数匹配与指数因子的关系清楚，示例及核对正确；本次略短且快约25秒，但单次差异不代表普遍提速。'),
 'binary_boundary':('更新理由、闭合答案边界与半开取样范围、严格收缩和重复值轨迹讲清，未声称实际运行；总结重复较多。',
                     '同样准确区分答案边界与取样范围，轨迹正确；逐轮展开与总结偏长，“开边界上保留”需结合闭合答案区间理解。本次更长更慢。'),
 'energy_multiplier':('链式法则与两项结构解释清楚，E=4、速率2、转折点不除v正确；另从K+U反推也有帮助，略超出单一思路。',
                       '补充二次型系数匹配，从目标反推也成立；但用户要一个方法，双路线加总结增长明显。本次更长更慢，不自动采纳。'),
 'relative_decay':('相对变化率、定积分与2mol/L结果正确；中间ln c应解释为选定单位后的数值，或直接从无量纲比值推导，不能仅因c>0就忽略量纲。',
                   '主要结构、单位和数例也正确，仍有带量纲ln c的记号歧义，多次重推、总结重复；比原版明显更长更慢，未显示稳定优势。'),
 'nonconstruction_control':('没有强套数学构造，区分支持不足与反证，假设例子完整且不出题；用未提供的评价标准时应始终保留示意身份。',
                           '同样保持哲学问题与来源边界，例子说明清楚，未加参数或新作业。本次略短较快，不能据此证明构造规则对所有非数学题更好。'),
}


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(OUT/'isolated-model')
    from studyforge.db import j
    from studyforge.exporters import export_document
    from studyforge.teaching import finish_explanation
    from studyforge.teaching_policy import REASONING_TEACHING_RULES
    from scripts.teaching_relation_candidate import BASELINE_RULES,RULES
    assert REASONING_TEACHING_RULES==BASELINE_RULES and REASONING_TEACHING_RULES!=RULES
    packet=load(PROBE/'cases.json');results=load(PROBE/'results.json');agents=load(AGENT/'results.json');audit=load(AUDIT/'results.json')
    assert len(results)==14 and all(r['status']=='completed' and r['model_requests']==1 for r in results)
    assert len(agents)==2 and all(r['status']=='completed' and r['model_requests']==2 for r in agents)
    assert audit['status']=='completed' and audit['model_requests']==1
    groups=[];table=[]
    for case in packet['cases']:
        pair={r['arm']:r for r in results if r['case']==case['id']};rows=[]
        for index,(arm,label) in enumerate([('baseline','当前规则'),('compact','反推关系候选 · 未集成')]):
            r=pair[arm];file=PROBE/r['answer_file'];text=file.read_text(encoding='utf-8')
            rows.append({'case':case['id'],'arm':arm,'label':label,'text':text,'review':NOTES[case['id']][index],
                'seconds':round(r['seconds'],2),'input_chars':r['input_characters'],'output_chars':len(text),'sha256':sha(file),
                'response_model':'deepseek-flash','usage':[t['usage'] for t in r['http_attempts']],'request':case['requests'][arm]})
        a,b=pair['baseline'],pair['compact']
        table.append('<tr><td>'+esc(case['title'])+'</td><td>'+f"{a['seconds']:.2f}秒／{a['output_characters']}字"+'</td><td>'+f"{b['seconds']:.2f}秒／{b['output_characters']}字"+'</td></tr>')
        source=case['source']+'\n\n核对点：\n'+'\n'.join(case['checks'])
        groups.append({'round':'导师实际入口' if case['role']=='tutor' else '文档实际提示构造','case':case['id'],'title':case['title'],
            'question':case['question'],'source':source,'rows':rows})
    tutor=next(r for r in agents if r['role']=='tutor');lecture=next(r for r in agents if r['role']=='lecture')
    raw=(AGENT/'lecture-final.md').read_text(encoding='utf-8');reviewed=(AUDIT/'快速核查后.md').read_text(encoding='utf-8')
    class NoModel:
        async def complete(self,*a,**kw):raise AssertionError('Do not add another call while arranging an existing summary.')
    final=asyncio.run(finish_explanation(NoModel(),reviewed,learning_mode='deep',explanation_style='balanced'))
    final_path=OUT/'实际讲解_快速核查与总结归位后.md';final_path.write_text(final,encoding='utf-8')
    reviewed_path=OUT/'快速核查组件原样输出.md';shutil.copyfile(AUDIT/'快速核查后.md',reviewed_path)
    word=OUT/'能量偏导与时间导数_实际讲解.docx'
    shutil.copyfile(export_document(final,'docx','能量偏导与时间导数 · 实际讲解','polynomial-lecture.docx'),word)
    with ZipFile(word) as z:
        tree=ET.fromstring(z.read('word/document.xml'));assert tree.findall('.//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath')
        assert '尚未再次独立复核' in ''.join(tree.itertext())
    groups.append({'round':'同一真实初稿的现有快速核查','case':'fast_review','title':'工具核对之后：额外文字推论仍须核查',
        'question':lecture['question'],'source':audit['source'],
        'rows':[{'case':'fast_review','arm':'raw','label':'工具支持的实际初稿 · 未另审','text':raw,
            'review':'工具的三个偏导核对均正确，链式法则主推导正确。但后文把势能偏导写成−kx，且将非零力直接等同非零功率；“v本身是独立函数”、零能量退化点等措辞也需核对。讲解明显偏长。',
            'seconds':round(lecture['seconds'],2),'input_chars':lecture['http_attempts'][0]['input_characters'],'output_chars':len(raw),
            'sha256':sha(AGENT/'lecture-final.md'),'response_model':'deepseek-flash','request':load(AGENT/'lecture-public-wire.json')},
           {'case':'fast_review','arm':'fast','label':'现有快速核查后 · 总结归位','text':final,
            'review':'现有1次快速核查用85.84秒定位两类问题，四处局部替换修正符号和非零功率限定，未重写全文。总结按原有函数归位，保留“未再次独立复核”。仍有冗长、独立函数措辞及修订例子对f的范围含混，不认证全篇正确。',
            'seconds':round(audit['seconds'],2),'input_chars':audit['http_attempts'][0]['input_characters'],'output_chars':len(final),
            'sha256':sha(final_path),'response_model':'deepseek-flash','request':load(AUDIT/'public-model-records.json')}]})
    checks=set()
    for name in ['polynomial-final-regression-20261016.xml','polynomial-delivery-regression-20261016.xml']:
        tests=ET.parse(ROOT/'build'/name).getroot().findall('.//testcase')
        assert tests and not any(t.find(k) is not None for t in tests for k in ('error','failure','skipped'))
        checks.update((t.get('classname'),t.get('name')) for t in tests)
    ui=load(UI/'ui-results.json');assert ui['passed'] and len(ui['checks'])==4 and not ui['external_model_requests']
    benchmark=load(ROOT/'build/polynomial-local-benchmark-20261016.json')
    shutil.copyfile(ROOT/'build/polynomial-local-benchmark-20261016.json',OUT/'本机耗时与分配记录.json')
    for file in ['电脑端数学核验.png','手机端数学核验.png']:shutil.copyfile(UI/file,OUT/file)
    (OUT/'实际工具公开输入与结果.json').write_text(j({role:load(AGENT/(role+'-public-wire.json')) for role in ('tutor','lecture')}),encoding='utf-8')
    (OUT/'实际快速核查记录.json').write_text(j(audit),encoding='utf-8')
    intro='''<header><div class="eyebrow">STUDYFORGE · CONSTRUCTION &amp; ALGEBRA · 2026-10-16</div><h1>核对关键代数，讲清构造与条件</h1><p>7组14份构造对照，2份实际工具讲解，1次现有快速核查。<a href="../../验收最新版.vbs">源码验收入口</a> · <a href="../../docs/构造思路与多项式核对验收.md">验收记录</a>。本轮未打包。</p>
<div class="notice">提示词候选没有稳定收益，未集成。已实施的是按需多项式恒等与形式偏导核对，不执行代码，不增加固定审查轮数。工具结果正确，额外文字推论仍可能错；初稿与核查后的残余问题均原样保留。</div></header>'''
    evidence='''<details class="prompt" open><summary>新增能力、实际结果与局限</summary><h2>按需本机代数核对</h2><p>开启AI工具后，导师、文档等共用Agent可按需使用同一数学工具。新增有理系数交换变量多项式恒等核对与形式偏导；变量最多6个，显式乘法和1至8的正整数幂，总次数24，展开128项，并限制运算量与数值大小。算术与向量原有操作保持。</p>
<p>结果返回正规形式和差值：例如错误配方的差值为−2B²，错误偏导的差值为−kx。恒等性看identical、导数一致性看matches，verified只表示计算完成。不支持函数、变量分母、无理数、矩阵或不等式；形式偏导把变量视作独立，不自动应用时间链式法则。附加条件下可能成立的等式，不能因不恒等就给学生判错。</p>
<p>无文件读写、网络或代码执行，只读模式可用；关闭通用工具则不调用。私有作业的符号、数值结果和验证错误不进入公开操作记录。工具按需使用后需要模型继续解释，会增加续答时间；不是每步强制核验或额外固定审核。</p>
<h2>实际模型如何使用</h2><ul><li>导师：2次模型请求、3次本机恒等核对，查出AC+B²应为AC−B²，区分恒等式与平方和非负条件，另处理A=0。</li><li>文档：2次模型请求、3次本机形式偏导核对，确认∂E/∂x=kx、∂E/∂v=mv，并用链式法则接回运动方程。但额外文字出现势能导数符号及非零力／功率问题。</li><li>对同一文档使用现有快速核查：1次请求、85.84秒，局部修正两类问题的四处表述；未再次独立复核，也没有因为这个试验增加软件默认审查轮数。</li></ul>
<p><a href="实际工具公开输入与结果.json">实际工具公开输入与结果</a> · <a href="实际快速核查记录.json">快速核查与修订记录</a>。均用DeepSeek Flash／high，合成材料，未用用户真实资料或其他聊天；不保存私有推理正文或密钥。</p>
<details><summary>实际导师完整回答（未另审）</summary><div id="actualRemediation" class="agent-preview"></div></details>
<h2>构造提示词实验：保留现有版本</h2><p>7题在采样前固定，前3题用于重点观察，后4题不再用于调词；实际导师入口或讲解提示构造，工具与联网关闭。每臂一次，仅替换一段构造指导，没有重复与盲评。现有规则多数已能回答；候选有的更清楚，有的更长，条件与措辞仍有缺口，不以单次耗时认定胜出。</p>
<div class="report-table"><table><thead><tr><th>问题</th><th>当前规则：耗时／字符</th><th>构造候选：耗时／字符</th></tr></thead><tbody>__ROWS__</tbody></table></div>
<h2>文件与检验</h2><p>__CHECKS__项相关去重回归、4项实际Electron电脑／配对HTTPS手机交互通过。覆盖精确代数、偏导、有限展开、变量分母拒绝、代码不执行、私有记录、原数值／向量、权限、模型协议、答案隔离、手机与指南。另以49组整数代入独立核对一份展开多项式，不能据此证明全软件或所有数学讲解正确。</p>
<p>本机21次样例：柯西恒等中位0.727毫秒，能量偏导0.519毫秒，超限展开拒绝14.235毫秒；Python临时分配峰值约57.44／31.15／78.93KiB。<a href="本机耗时与分配记录.json">完整记录</a>仅限这些计算，不能代替全应用RAM、云模型或完整视频速度。</p>
<p><a href="能量偏导与时间导数_实际讲解.docx">实际讲解Word</a> · <a href="实际讲解_快速核查与总结归位后.md">相同正文Markdown</a> · <a href="快速核查组件原样输出.md">核查组件原样输出</a>。采用实际模型输出和现有局部替换、总结归位、Word输出函数，没有人工润色；Word容器、正文与原生公式已核对，未在Microsoft Word视觉验收。</p>
<details><summary>查看两端工具交互截图</summary><p><img src="电脑端数学核验.png" style="max-width:100%" alt="电脑端数学工具"></p><p><img src="手机端数学核验.png" style="max-width:390px;width:100%" alt="手机端数学工具"></p></details>
<p>完全退出旧源码版后双击<a href="../../验收最新版.vbs">验收最新版</a>。可要求导师“核对这条多项式恒等式，再解释条件”；模型仍可能不调用或误述结果。指南同步，手机壳v49。没有重测真实安卓设备、完整长书／视频、所有模型账号或全软件总内存，本轮未打包。</p></details>'''
    evidence=evidence.replace('__ROWS__',''.join(table)).replace('__CHECKS__',str(len(checks)))
    page=re.sub(r'<header>.*?</header>',lambda _:intro,TEMPLATE,flags=re.S).replace('<main>','<main>'+evidence,1)
    page=page.replace('<title>StudyForge · 讲解质量真实对照</title>','<title>构造思路与多项式核对实际对照 · StudyForge</title>')
    page=page.replace('grid-template-columns:repeat(3,minmax(0,1fr))','grid-template-columns:repeat(2,minmax(0,1fr))')
    page=page.replace('</style>','.report-table{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}td,th{border:1px solid #d8e2df;padding:10px;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}.agent-preview{background:white;padding:16px;border:1px solid #d8e2df;border-radius:12px;overflow-x:auto;max-width:100%}.lesson-math.display-math{display:block;overflow-x:auto;overflow-y:hidden;padding:6px 0}.katex-display{overflow:visible}</style>',1)
    page=page.replace('查看本次提供的完整合成原资料','查看合成原料与人工核对点').replace('核对实际请求、用量与原文指纹','核对公开输入、用量与回答指纹')
    page=page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。','原样讲解、工具结果、公式渲染和字体嵌入本页；切换不请求模型。人工评价与模型核查均有局限，残余问题保留，不认证整篇正确。')
    css=(ROOT/'web/vendor/katex.css').read_text(encoding='utf-8')
    css=re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((ROOT/'web/vendor/fonts'/m[1]).read_bytes()).decode()+')',css)
    css=re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
    page=page.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',j({'groups':groups,'count':16,'failures':[]}).replace('<','\\u003c'))
    page=page.replace('__LIBRARIES__','\n'.join(inline_script((ROOT/'web/vendor'/n).read_text(encoding='utf-8')) for n in ['marked.js','purify.js','katex.js']))
    page=page.replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    text=(AGENT/'tutor-final.md').read_text(encoding='utf-8')
    snippet='renderLessonText(document.getElementById("actualRemediation"),'+j(text).replace('<','\\u003c')+');'
    before,after=page.rsplit('</body>',1);page=before+'<script>'+inline_script(snippet)+'</script></body>'+after
    target=OUT/'构造思路与多项式核对实际对照.html';target.write_text(page,encoding='utf-8')
    (OUT/'manifest.json').write_text(j({'answers':16,'groups':8,'report_table_rows':[7],'actual_remediation':True,
        'program_checks':len(checks),'ui_checks':4,'candidate_adopted':False,'capability_implemented':'bounded_polynomial_algebra',
        'real_prompt_requests':14,'real_agent_requests':4,'real_review_requests':1,'word_sha256':sha(word),
        'output_sha256':sha(target),'package_created':False}),encoding='utf-8')
    print(j({'output':str(target),'checks':len(checks),'candidate_adopted':False,'model_requests':19}))


if __name__=='__main__':main()
