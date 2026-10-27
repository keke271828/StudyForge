"""Offline review of actual teaching, grading failure, recovery and reteaching."""
import base64
from fractions import Fraction
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
PROBE=ROOT/'build/teaching-step-real-20261016-1'
OLD=ROOT/'build/step-feedback-real-20261016-1'
NEW=ROOT/'build/step-feedback-real-20261016-2'
OUT=ROOT/'build/teaching-step-acceptance-20261016'
NOTES={
 'gauss_factor':('承认常数及常矢量可提出积分，逐面算到0；没有重现上一轮全盘否定提出常数的问题，末尾稍重复。',
                 '同样保留提出常数，区分总面积与有向面积和，算例完整且较短；不能把这一次差异推广为普遍质量提升。'),
 'divide_zero':('分支、零解和解集正确；额外讨论乘0仍保持等式，但未充分区分保持等式与保持等价求解，容易给初学者混淆。解释和总结反复较多。',
                '保留非零分支，并补上零解；避免了原版的乘0旁支。正文与总结仍多次重复，1858字符并不简洁，本次也更慢。'),
 'gas_temperature':('两态量和单位正确，保留原公式，解释只算体积为何得到50kPa；过程较长。',
                    '同样得到100kPa，算式、温度和体积效应对应清楚，较紧凑；“你把温度仍当300K”是对这段计算的解释，不应外推心理诊断。'),
 'feedback_gain':('给定模型的倍率、数例、收敛范围正确，明确不是具体生物机制；不把所有负反馈当稳定。',
                  '方向与步长区别清楚，数例正确；比原版更长。“稳定”在这里指回归到零，不能外推到所有稳定性定义；零偏差时修正也为零，没有非零方向。'),
 'description_norm':('保留调查并补评价前提，原文与补充区分；多处扩展偏长。章程约束力本身也须被接受，不能只凭一个规则存在就证明规范正当性。',
                     '在同一决策中保留调查作用，假设原则与原材料分开，较短；“调查加章程足以推出决定”仍应理解为按已接受的规则推导，不等于规则本身已获辩护。'),
 'alias_slots':('初始共享、替换槽位和修改旧对象均解释正确，静态结果正确，未冒称执行。',
                 '同样正确，沿两次操作接续解释，略短；两版都能完成这个目标，不能只凭长度宣称胜出。'),
 'valid_division':('直接确认正确，除以正数与AM-GM依据齐全，没有为纠错挑错。',
                    '同样确认正确，且指出AM-GM允许非负的更广范围；关键条件齐全。略长但本次较快。'),
 'valid_observation':('确认总结正确，区分未证明有影响与未证明无影响；把相关非零、回归系数非零等与非独立并列时仍需具体定义，不能无条件等同所有关联指标。',
                       '基本判断正确，未将混杂未排除当作无因果；“不能认定可能影响”与“不能排除有影响”措辞容易绕，且追加研究证据略超出仅核对的要求。此例未明显优于原版。'),
}


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=True,parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(OUT/'isolated-model')
    from studyforge import homework
    from studyforge.db import j
    from studyforge.exporters import export_document
    from studyforge.teaching_policy import POLICY_VERSION,REASONING_TEACHING_RULES
    from scripts.teaching_step_candidate import RULES
    assert REASONING_TEACHING_RULES==RULES
    packet=load(PROBE/'cases.json');results=load(PROBE/'results.json')
    assert len(results)==16 and all(r['status']=='completed' and r['model_requests']==1 for r in results)
    groups=[];table=[];faster=shorter=0
    for case in packet['cases']:
        pair={r['arm']:r for r in results if r['case']==case['id']};rows=[]
        for index,(arm,label) in enumerate([('baseline','修改前'),('compact','保留合法步骤 · 当前规则')]):
            row=pair[arm];path=PROBE/row['answer_file'];text=path.read_text(encoding='utf-8')
            rows.append({'case':case['id'],'arm':arm,'label':label,'text':text,'review':NOTES[case['id']][index],
                'seconds':round(row['seconds'],2),'input_chars':row['input_characters'],'output_chars':len(text),
                'sha256':sha(path),'response_model':'deepseek-flash','usage':[t['usage'] for t in row['http_attempts']],
                'request':case['requests'][arm]})
        a,b=pair['baseline'],pair['compact'];faster+=b['seconds']<a['seconds'];shorter+=b['output_characters']<a['output_characters']
        table.append('<tr><td>'+esc(case['title'])+'</td><td>'+('后半组' if case['phase']=='heldout' else '前半组')+'</td><td>'+f"{a['seconds']:.2f}秒／{a['output_characters']}字"+'</td><td>'+f"{b['seconds']:.2f}秒／{b['output_characters']}字"+'</td></tr>')
        source=case['source']+'\n\n已有公开背景：\n'+'\n'.join(m['content'] for m in case.get('history',[]))+'\n\n人工核对点：\n'+'\n'.join(case['checks'])
        groups.append({'round':'导师实际入口' if case['role']=='tutor' else '文档实际提示构造','case':case['id'],'title':case['title'],
            'question':case['question'],'source':source,'rows':rows})
    checks=set()
    for name in ['teaching-step-regression-20261016.xml','teaching-step-delivery-regression-20261016.xml']:
        root=ET.parse(ROOT/'build'/name).getroot()
        tests=root.findall('.//testcase')
        assert tests and not any(t.find(k) is not None for t in tests for k in ('failure','error','skipped'))
        checks.update((t.get('classname'),t.get('name')) for t in tests)
    old=load(OLD/'results.json');fresh=load(NEW/'results.json');records=load(NEW/'public-model-records.json')
    assert len(old)==2 and all(r['status']=='failed' for r in old)
    assert all(r['status']=='completed' and not r['grade']['grading_verification_required'] for r in fresh)
    assert fresh[0]['grade']['scores']==[100] and fresh[1]['grade']['scores']==[40]
    assert fresh[1]['remediation']['status']=='completed'
    replay=load(OLD/'local-replay.json');assert len(replay)==4 and all(r['all_text_preserved'] and r['score_unchanged'] for r in replay)
    assert len(records)==6 and len(load(NEW/'request-metrics.json'))==6
    (OUT/'修复前的原始模型反馈.json').write_text(j(load(OLD/'public-model-records.json')),encoding='utf-8')
    (OUT/'修复后的批改与补讲原始响应.json').write_text(j(records),encoding='utf-8')
    case=fresh[1]['case'];analysis=fresh[1]['remediation']['analysis'];grade=fresh[1]['grade']
    worksheet={'title':'高斯定律 · 真实批改与补讲',
        'questions_json':j([{'index':0,'topic':'高斯定律','question':case['question']}]),
        'solutions_json':j([{'index':0,'solution':case['solution'],'rubric':case['rubric']}])}
    body=homework.report_document({'answers_json':j([case['answer']])},worksheet,grade,analysis)
    path=export_document(body,'docx',worksheet['title'],'step-feedback.docx')
    word=OUT/'实际批改与错因补讲.docx';shutil.copyfile(path,word)
    (OUT/'实际批改与错因补讲.md').write_text(body,encoding='utf-8')
    with ZipFile(word) as archive:
        tree=ET.fromstring(archive.read('word/document.xml'))
        assert '40' in ''.join(tree.itertext()) and tree.findall('.//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath')
    # Finite independent checks, not a certificate of a general proof.
    F=Fraction;gain=lambda g:[(1-g)**k for k in range(6)]
    assert gain(F(1,2))==[F(1),F(1,2),F(1,4),F(1,8),F(1,16),F(1,32)]
    assert gain(F(3))==[1,-2,4,-8,16,-32]
    assert F(100)*F(600,300)*F(1,2)==100
    assert sum([3*4,-3*4,0,0,0,0])==0
    code=[[0]]*2;assert code[0] is code[1];code[0]=[7];code[1].append(8);assert code==[[7],[0,8]]
    (OUT/'本机有限核对.json').write_text(j({'scope':'仅核对样例的数值及本段固定代码，不证明一般定理或整篇正确。',
        'feedback_half':[str(x) for x in gain(F(1,2))],'feedback_three':[str(x) for x in gain(F(3))],
        'pressure_kPa':100,'cube_net_flux':0,'python_list':code,'external_model_requests':0}),encoding='utf-8')
    intro='''<header><div class="eyebrow">STUDYFORGE · LEARNING QUALITY · 2026-10-16</div><h1>保留正确的思路，修准真正出错的那一步</h1>
<p>8组16份真实讲解对照，另有两轮批改与一次补讲。<a href="../../验收最新版.vbs">源码验收入口</a> · <a href="../../docs/教学纠错与批改反馈验收.md">验收记录</a>。本轮未打包。</p>
<div class="notice">本轮采用一处小范围教学修订：保留合法步骤，在原情境中补全错误；不增加固定模型轮次。另修复单题多个评分点评语导致批改失败的问题。真实回答仍有重复和措辞缺陷，不能把结构通过或两模型同分当作整篇正确。</div></header>'''
    evidence='''<details class="prompt" open><summary>本轮改动、原始失败与实际结果</summary><h2>讲解规则：小范围改进</h2>
<p>同一DeepSeek Flash／high，工具与联网关闭，使用实际导师入口与讲解构造函数。八题在采样前固定，后四题未用于再次调规则；每臂仅一次，没有重复和盲评。题目含明确要求保留正确步骤的情形，会帮助两臂，不把两版都讲清算作新版独有收益。</p>
<p>本轮只替换共同规则中的一句话，输入增加45字符。要求保留有效步骤，定位缺条件或不成立之处，再在原情境接上正确推导；学生原本正确时应确认。其余来源、语言、模式、模型、推理与审查档位保持。当前版本：__VERSION__。</p>
<div class="report-table"><table><thead><tr><th>题目</th><th>组别</th><th>修改前：耗时／字符</th><th>修改后：耗时／字符</th></tr></thead><tbody>__ROWS__</tbody></table></div>
<p>本次5组更快、3组更慢，6组正文较短、2组更长。部分回答更集中，但现有版本来就能回答多数主问题；社会科学的规范前提与认识论措辞、简单题反复总结仍须改进。不将这些单次差异宣布为总体速度或教学质量排名。</p>
<h2>修复：合理批改不该因按评分点分段而失败</h2><p>修复前两道单题均失败。原始模型给分分别为100和40，但把每个评分点拆成feedback数组的多个元素；每题一条的校验拒绝，格式修复后仍拆分。本机重放这四条原始响应，完整合并单题评语后均通过结构校验，分数及全部文字不变，零模型请求。</p>
<p>只对一道题、各点评语均为有效字符串的情况作无歧义合并，并保存整理记录。多题不猜分组，空白或错误字段不丢弃、不补造；格式修复会明确指出题数和当前条数。两次独立评分、必要的分歧裁决、通过线、疑点评分和提交前答案隔离继续生效。</p>
<h3>真实复测</h3><ul><li>等价正确证明：两次独立评分均100，未因多定义一个未使用的符号扣正确性分。第二次返回多了一个右方括号，现有一次格式修复后完成；共3次模型响应。</li><li>高斯定律的部分正确解答：两次独立评分均40，保留写出积分／提出常数的40分，另两点评为未满足。按本次明示评分标准判断，共2次模型响应。</li><li>针对性补讲：1次响应，从学生实际写出的“剩下的面积积分是六个面的面积和6A”定位错误，保留合法提出常数的步骤；历史上问过电通量仅作线索，不独自定错因。补讲的implementation分类并非唯一可能的教学分类，不据此认证长期能力。</li></ul>
<p><a href="修复前的原始模型反馈.json">修复前4条原始响应</a> · <a href="修复后的批改与补讲原始响应.json">修复后6条完整响应及公开输入</a>。第一轮旧记录只记录完成响应，未测HTTP尝试次数；第二轮另记录6次实际HTTP返回。不保存密钥或私有推理正文。</p>
<h3>实际补讲正文</h3><div id="actualRemediation" class="feedback-sample"></div>
<p><a href="实际批改与错因补讲.docx">实际批改与错因补讲 · Word</a> · <a href="实际批改与错因补讲.md">同一正文 · Markdown</a>。由原始评分和补讲结果经现有报告与Word输出器生成，没有润色。Word容器及原生公式检查通过，未在Microsoft Word作视觉验收。</p>
<h2>程序与交付</h2><p>__CHECKS__项相关去重回归通过，含真实API受控提交、先交付解析、独立评分、单题多评语完整进入DOCX、错因与补讲、79／80边界、多题拒绝猜归属、空白／非文本反馈修复、历史恢复与答案隔离。既有测试与补充组重叠只计一次。</p>
<p>本机另核对立方体数值通量、两态压强、两组反馈序列，并实际执行此处固定的Python列表样例，均与已审读的结果一致。<a href="本机有限核对.json">有限核对记录</a>只说明这些具体例子，不是完整定理验证，也不是用户能力证据。</p>
<p>完全退出旧源码版后双击<a href="../../验收最新版.vbs">验收最新版</a>。新教学规则随导师和讲解请求生效，无需额外开关；批改沿原入口使用。指南同步，手机公开页面壳v48。本轮没有重测真实安卓、全软件内存、长书或视频总速度，也没有生成安装包。</p></details>'''
    evidence=evidence.replace('__VERSION__',esc(POLICY_VERSION)).replace('__ROWS__',''.join(table)).replace('__CHECKS__',str(len(checks)))
    page=re.sub(r'<header>.*?</header>',lambda _:intro,TEMPLATE,flags=re.S).replace('<main>','<main>'+evidence,1)
    page=page.replace('<title>StudyForge · 讲解质量真实对照</title>','<title>教学纠错与批改反馈实际对照 · StudyForge</title>')
    page=page.replace('grid-template-columns:repeat(3,minmax(0,1fr))','grid-template-columns:repeat(2,minmax(0,1fr))')
    page=page.replace('</style>','.report-table{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}td,th{border:1px solid #d8e2df;padding:10px;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}.feedback-sample{padding:20px;background:white;border:1px solid #d8e2df;border-radius:12px;min-width:0;max-width:100%;overflow-x:auto}.lesson-math.display-math{display:block;overflow:auto}.katex-display{overflow:auto}pre{word-break:break-word}</style>',1)
    page=page.replace('查看本次提供的完整合成原资料','查看合成材料、背景和核对点').replace('核对实际请求、用量与原文指纹','核对公开输入、用量与回答指纹')
    page=page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。','全部16份讲解、实际补讲和渲染器嵌入此页；切换不请求模型。原始缺陷均保留，人工评价也可核对，不是通用教材认证。')
    css=(ROOT/'web/vendor/katex.css').read_text(encoding='utf-8')
    css=re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((ROOT/'web/vendor/fonts'/m[1]).read_bytes()).decode()+')',css)
    css=re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
    page=page.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',j({'groups':groups,'count':16,'failures':[]}).replace('<','\\u003c'))
    page=page.replace('__LIBRARIES__','\n'.join(inline_script((ROOT/'web/vendor'/n).read_text(encoding='utf-8')) for n in ['marked.js','purify.js','katex.js']))
    page=page.replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    snippet='renderLessonText(document.getElementById("actualRemediation"),'+j(analysis['items'][0]['explanation']).replace('<','\\u003c')+');'
    before,after=page.rsplit('</body>',1)
    page=before+'<script>'+inline_script(snippet)+'</script></body>'+after
    target=OUT/'教学纠错与批改反馈实际对照.html';target.write_text(page,encoding='utf-8')
    manifest={'answers':16,'groups':8,'report_table_rows':[8],'program_checks':len(checks),'policy_version':POLICY_VERSION,
        'candidate_adopted':True,'real_teaching_responses':16,'old_grading_responses':4,'new_grading_responses':6,
        'new_grading_http_responses':6,'faster_cases':faster,'shorter_cases':shorter,'actual_remediation':True,
        'word_sha256':sha(word),'output_sha256':sha(target),'package_created':False}
    (OUT/'manifest.json').write_text(j(manifest),encoding='utf-8')
    print(j({'output':str(target),'program_checks':len(checks),'answers':16,'real_feedback_responses':10}))


if __name__=='__main__':main()
