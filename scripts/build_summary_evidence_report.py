"""Offline real summary comparison and bounded local-workflow evidence."""
import base64
from html import escape as esc
import hashlib
import json
from pathlib import Path
import re
import shutil
from xml.etree import ElementTree

from scripts.build_teaching_comparison import TEMPLATE,inline_script

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/summary-body-evidence-acceptance-20261016'
PROBE=ROOT/'build/summary-body-evidence-20261016-1'
FLOW=ROOT/'build/summary-evidence-workflow-20261016-1'
NOTES={
 'math':{'baseline':'没有编造未提供的参数，明确说明具体条件未进入输入；总结因此较笼统。这是输入遗漏，不应简单判为模型答错。',
    'with_body':'补回更新式、0<q<2、任意初值与q=0、2的边界，信息更具体。但“不能扩大为所有初值”需与参数限制连读：合法q下本来就覆盖任意实初值，措辞仍可更清楚。'},
 'causal':{'baseline':'保留随机提醒与比较对象的主线，未编造差异大小。对“未说明具体对象”的表述仍含糊，需要区分分配单位与实际分配的干预。',
    'with_body':'保留假设实验身份、平均高3分、随机提醒与实际行为的区别，以及未排除其他路径和依从性的限制；没有把行为本身的因果作用写成已经证明。但“原文未确认”的来源措辞不准确：本次提供的是AI讲解，不是原文件。'},
 'chemistry':{'baseline':'明确不补未给出的移动方向，保留总压强与分压的区分。第一段“压力变化会影响平衡方向”偏笼统，后面才补边界。',
    'with_body':'补回恒温压缩理想混合气体的语境、计量数差及恒温恒容加惰性气体不移动的反例；这些来自传入AI讲解片段，并非本次新核验的教材事实。'},
}


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=True,parents=True);groups=[];table=[]
    inputs=load(PROBE/'input-cases.json');results=load(PROBE/'results.json')
    assert len(results)==6 and all(r['status']=='completed' and r['model_requests']==1 for r in results)
    for name,case in inputs.items():
        plans=load(PROBE/(name+'-plans.json'));pair={r['arm']:r for r in results if r['case']==name};rows=[]
        for arm,label in [('baseline','原有目录与小结输入'),('with_body','增加正文条件片段')]:
            row=pair[arm];file=PROBE/row['answer_file'];text=file.read_text(encoding='utf-8')
            rows.append({'case':name,'arm':arm,'label':label,'text':text,'review':NOTES[name][arm],
                'seconds':round(row['seconds'],2),'output_chars':len(text),'input_chars':row['input_characters'],
                'sha256':sha(file),'response_model':'deepseek-flash','usage':[r['usage'] for r in row['http_attempts']],
                'request':load(PROBE/(name+'-'+arm+'-records.json'))})
        old,new=(pair[a] for a in ('baseline','with_body'))
        table.append('<tr><td>'+esc(case['title'])+'</td><td>'+f"{old['seconds']:.2f}秒 / {old['input_characters']}字符"+'</td><td>'+f"{new['seconds']:.2f}秒 / {new['input_characters']}字符"+'</td></tr>')
        groups.append({'round':'同一总结规则与模型','case':name,'title':case['title'],
            'question':'比较模型能否在总结中保留具体条件、反例与已知范围；不是在测整本电子书的理解或一般教学准确率。',
            'source':'合成已完成AI讲解的中部正文：\n'+case['body']+'\n\n两个原有小结：\n'+'\n'.join(case['recaps'])+
                '\n\n每个合成章节加入重复占位段，触发节选；不是实际电子书。这轮总结输入上限6000字符。\n\n原输入：\n'+plans['baseline']['text']+
                '\n\n补片段后输入：\n'+plans['with_body']['text'],'rows':rows})
    flow=load(FLOW/'results.json');local=load(ROOT/'build/summary-evidence-local-overhead-20261016.json')
    assert flow['passed'] and flow['controlled_requests']==5 and flow['summary_requests']==1 and not flow['external_model_requests']
    tests=ElementTree.parse(ROOT/'build/summary-evidence-final-regression-20261016.xml').getroot().findall('.//testcase')
    assert tests and not any(c.find(k) is not None for c in tests for k in ('failure','error','skipped'))
    shutil.copyfile(FLOW/flow['docx_file'],OUT/flow['docx_file'])
    intro='''<header><div class="eyebrow">STUDYFORGE · SUMMARY EVIDENCE · 2026-10-16</div><h1>长讲解的总结：把正文条件带回来</h1>
<p>3组、6份真实原样总结。<a href="../../验收最新版.vbs">打开当前源码版</a> · <a href="../../web/help/guide.html#outputs">软件内指南</a>。本轮未打包。</p>
<div class="notice">正文超出总结输入上限后，原流程可能只传目录和已有小结，遗漏正文中部的适用条件。现利用预算余量补入少量逐字条件片段，保留位置和指纹；不替换原有输入、不增加固定模型调用。片段仍是可能有误的AI讲解，不能视为原文或新核查结果。</div></header>'''
    evidence='''<details class="prompt"><summary>实施边界、计时和验收记录</summary><h2>具体改动</h2><p>仅在总结输入确实节选、所有章节仍在原有输入中且预算有余量时补充。每次最多增加3000字符、16段；完整输入、不够空间、已有章节被省略时沿用原方案。跳过原文引用块、代码、已有小结和核查提示，完整保留被选段落，超长段不截断。逐字位置与哈希随成果保存，不写入学习画像。</p>
<p>首次讲解仍按原流程读取所选原文件。这里补充的是全文总结的辅助输入，不把预览或AI笔记拿来替代首次原文阅读。提示词、模型、推理强度、审查档位、章节顺序和原有疑点记录保持。</p>
<h2>真实请求</h2><p>DeepSeek Flash，服务返回deepseek-flash，high；同一总结系统提示，两臂只改变输入片段。工具与联网关闭，每臂1次、共6次真实请求。使用合成长讲解、6000字符辅助预算，未做盲评或重复。不是网页端比较，也不测PDF／视频识别或整体生成时间。</p>
<div class="report-table"><table><thead><tr><th>题目</th><th>原输入</th><th>补条件后</th></tr></thead><tbody>'''+''.join(table)+'''</tbody></table></div>
<p>三份新版总结保留了更多已提供的具体条件。原版多数明确表示输入没有细节，不能把它们都判为错误。数学总结仍有需结合前提阅读的措辞；片段机制不保证最终结论必然正确。耗时有增有减，数学本次增加约4.25秒，不宣称普遍提速或输入增加零开销。</p>
<h2>程序和本机开销</h2><p>__TEST_COUNT__项相关去重回归通过。完整受控生成包含2章撰写、2次快速核查、1次全文总结，共5次受控请求、0次外部请求；实际写出唯一所选DOCX，原文件重新读取，未用预览，未新增习题或分数。核对文件容器与正文，未做Microsoft Word视觉验收。</p>
<p>本机片段整理另测10章、约90万字符，7次中位约__MEDIAN__毫秒，额外Python分配峰值约__PEAK__MiB；不含模型请求、原文识别、文档排版或软件总内存。只说明这个小改动的本机整理开销，不能据此称原有卡顿或总内存问题已解决。</p>
<p><a href="长讲解总结条件流程样例.docx">下载受控Word流程样例</a>。使用软件按原方式生成长讲解即可，无需增加开关。<a href="../../验收最新版.vbs">源码验收入口</a>需要在旧源码版完全退出后重新打开，已安装旧版没有自动变化。</p></details>'''
    evidence=evidence.replace('__TEST_COUNT__',str(len(tests))).replace('__MEDIAN__',f"{local['median_seconds']*1000:.1f}").replace('__PEAK__',f"{local['extra_python_allocation_peak_bytes']/1024**2:.2f}")
    page=re.sub(r'<header>.*?</header>',lambda _:intro,TEMPLATE,flags=re.S)
    page=page.replace('<main>','<main>'+evidence,1).replace('<title>StudyForge · 讲解质量真实对照</title>','<title>长讲解总结条件保留实际对照 · StudyForge</title>')
    page=page.replace('grid-template-columns:repeat(3,minmax(0,1fr))','grid-template-columns:repeat(2,minmax(0,1fr))')
    page=page.replace('</style>','.report-table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d8e2df;padding:10px;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}pre{word-break:break-word}</style>',1)
    page=page.replace('本次提供的完整合成原资料','本组的合成讲解片段与两臂完整输入').replace('核对实际请求、用量与原文指纹','核对实际公开请求、用量与回答指纹')
    page=page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。','全部总结、渲染器与字体已嵌入此页；切换不发送模型请求。原样回答可能仍有错误，不能作为已审核定稿教材。')
    css=(ROOT/'web/vendor/katex.css').read_text(encoding='utf-8')
    css=re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((ROOT/'web/vendor/fonts'/m[1]).read_bytes()).decode()+')',css)
    css=re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
    data={'groups':groups,'count':6,'failures':[]}
    page=page.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',json.dumps(data,ensure_ascii=False).replace('<','\\u003c'))
    page=page.replace('__LIBRARIES__','\n'.join(inline_script((ROOT/'web/vendor'/n).read_text(encoding='utf-8')) for n in ['marked.js','purify.js','katex.js']))
    page=page.replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    target=OUT/'长讲解总结条件保留实际对照.html';target.write_text(page,encoding='utf-8')
    manifest={'date':'2026-10-16','answers':6,'groups':3,'real_model_requests':6,'program_checks':len(tests),'report_table_rows':[3],
        'workflow':flow,'local_overhead':local,'package_created':False,'output_sha256':sha(target)}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'output':str(target),'answers':6,'program_checks':len(tests)},ensure_ascii=True))


if __name__=='__main__':main()
