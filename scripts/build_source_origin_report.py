"""Offline raw model comparisons; known source roles are not truth certificates."""
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
OUT=ROOT/'build/source-origin-acceptance-20261016'
PROBE=ROOT/'build/source-origin-real-20261016-1'
FLOW=ROOT/'build/source-origin-workflow-20261016-3'
NOTES={
 'summary':{
    'baseline':'这次旧规则已经保留假设实验、随机提醒与行为的区别，没有重现上一轮“原文未确认”的误称。不能把它判为本轮失败。',
    'with_origin':'明确称为“已提供的讲解”，同样保留随机化对象、3分及限制；没有声称进行了新查证。一次成功不能保证所有总结都不再误述。'},
 'generated':{
    'baseline':'主要推理和平均／个体的区分有帮助，也注意到未附教材。但中途说“原文说”，没有识别这是本软件的AI成果；末尾仍有把转述实验写成所获结论的风险。篇幅较长。',
    'with_origin':'开头明确是一份讲解而非教材原文，引用位置指向本文件；保留未附教材和报告的限制。没有因其由AI生成而拒绝解释。但正文与总结仍偏长，一些“支持平均效应”的措辞要与实验实施和证据限制连读；这次耗时明显增加。'},
 'mixed':{
    'baseline':'正确发现随机提醒不等于实际记笔记，也保留假设例子身份。后面把“没有保证／没有排除”写成“两个条件都不成立”，把尚未确证说得太强；两份资料的身份也未明确区分。',
    'with_origin':'同时指出旧讲解的AI身份与具体推理错误，依据导入片段中的设计限制判断，未仅凭作者身份否定。仍引入工具变量等扩展，超过讲清当前核心逻辑的最低需要；不是无瑕的最终教材。'},
 'plain':{
    'baseline':'讲清正ε取值的合法性、开邻域取等号的边界和统一N；有数值例子与门槛类比。对当前问题已经有实质帮助。',
    'with_origin':'同样讲清量词、几何动机和max门槛，没有强插AI来源免责声明或拒答。两版各有展开差异，本例没有稳定质量胜负，不能把新规则普遍评为更好。'},
}


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=True,parents=True);groups=[];table=[]
    cases=load(PROBE/'cases.json');results=load(PROBE/'results.json')
    assert len(results)==8 and all(r['status']=='completed' and r['model_requests']==1 for r in results)
    for case in cases:
        name=case['name'];pair={r['arm']:r for r in results if r['case']==name};rows=[]
        for arm,label in [('baseline','未传递本轮资料身份规则'),('with_origin','传递资料身份与来源规则')]:
            row=pair[arm];file=PROBE/row['answer_file'];text=file.read_text(encoding='utf-8')
            rows.append({'case':name,'arm':arm,'label':label,'text':text,'review':NOTES[name][arm],
                'seconds':round(row['seconds'],2),'output_chars':len(text),'input_chars':row['input_characters'],
                'sha256':sha(file),'response_model':'deepseek-flash','usage':[r['usage'] for r in row['http_attempts']],
                'request':case['requests'][arm]})
        a,b=pair['baseline'],pair['with_origin']
        table.append('<tr><td>'+esc(case['title'])+'</td><td>'+f"{a['seconds']:.2f}秒"+'</td><td>'+f"{b['seconds']:.2f}秒"+'</td></tr>')
        groups.append({'round':'同一模型，四类来源输入','case':name,'title':case['title'],
            'question':case['question'],'source':case['source'],'rows':rows})
    flow=load(FLOW/'results.json')
    assert flow['passed'] and flow['controlled_requests']==2 and not flow['external_model_requests'] and flow['unselected_parent_not_read']
    alignment=load(PROBE/'current-input-alignment.json')
    assert alignment['passed'] and len(alignment['checks'])==4 and not alignment['external_requests']
    tests=ElementTree.parse(ROOT/'build/source-origin-final-regression-20261016.xml').getroot().findall('.//testcase')
    assert tests and not any(c.find(k) is not None for c in tests for k in ('failure','error','skipped'))
    unique={(c.get('classname'),c.get('name')) for c in tests};assert len(unique)==len(tests)
    shutil.copyfile(FLOW/flow['docx_file'],OUT/flow['docx_file'])
    intro='''<header><div class="eyebrow">STUDYFORGE · MATERIAL ORIGINS · 2026-10-16</div><h1>读到文件，不等于核对过它的原始依据</h1>
<p>4组、8份真实原样回答。<a href="../../验收最新版.vbs">打开当前源码版</a> · <a href="../../web/help/guide.html#outputs">软件内指南</a>。本轮未打包。</p>
<div class="notice">本轮让已知AI成果身份随所选文件传入导师、讲解、通读与工具读取；总结明确依据是已生成讲解。身份说明来自本机已有成果关联，不是对作者或内容的认证，不增加固定模型请求，也不会自动打开未选教材。普通导入文件仍可正常解释。</div></header>'''
    evidence='''<details class="prompt"><summary>本轮改动、真实耗时与检验</summary><h2>具体修复</h2>
<p>此前生成文件在资料快选中已被归为成果，但模型输入并不总能得到这一身份。文件读取方法“original_file”也可能被误解成已经核对原始资料。现在用本项目已有成果关联区分已知AI成果与其他导入文件，选段沿已有范围关系追溯身份；只查关联，不回读未选原文件。原父资料删除则记录来源关系不完整，不伪称认证。跨项目归属冲突会在读内容前停止。</p>
<p>视频原文档按整理的来源记录处理；外部附加文件和未知类型不一律认定AI创作。长资料每段保留适用身份。同名资料用现有资料ID区分，来源名称和位置继续保留。原文件内容、范围选择、字节与内容指纹不被身份说明改写；身份不证明推导正确，也不因为是AI成果就一概否定。全文总结称输入为已提供讲解，不能声称新核查过原文。旧导出的文件不会自动改写。</p>
<h2>真实对照的范围</h2><p>DeepSeek Flash，服务返回deepseek-flash，high；工具、联网与其他聊天关闭，每臂1次，共8次实际请求。总结对照使用上一轮相同用户输入和实际旧系统提示；另外三组使用当前生成入口捕获输入，移除本轮来源身份与相应措辞来构造对照，并非重跑整套历史安装包。材料均为合成短文本；不测书库OCR、视频或整份任务耗时。没有盲评和重复，原样回答可下载。</p>
<div class="report-table"><table><thead><tr><th>主题</th><th>未传递本轮身份</th><th>传递身份</th></tr></thead><tbody>'''+''.join(table)+'''</tbody></table></div>
<p>本轮新版在旧成果与混合材料中明确身份，仍继续解释具体逻辑。旧版总结这次也没有误称，普通数学题两版都讲清了主要理由。不能据此宣称一般准确率或教学质量全面提高；仍有过长、扩展过多和条件措辞需读者核对的问题。</p>
<p>来源说明本机生成，不增加固定审查轮次，但不承诺速度不变：本次单一成果题约40.21→70.49秒，其他样例有快有慢。输入、推理、输出与服务波动均可能影响时间，不能把这一组差异全部归因为某句话。没有因此调低模型或推理强度。</p>
<h2>程序与完整流程</h2><p>__COUNT__项相关去重回归通过：原文件读取、选段、同名与超长资料、工具缓存、PDF指定页、MCP、原对话与教学要求、审查、画像范围和既有书库参考。另有一条完整受控DOCX生成：1次撰写＋1次快速核查，共2次受控请求、0次外部模型请求；所选AI成果的身份进入两项输入与成果记录，未选教材文件不存在仍可完成，未读取其预览，也未出题或评分。</p>
<p><a href="引用已有AI讲解的Word流程样例.docx">下载受控Word流程样例</a>。这一文件用于检查生成路径与身份传递，正文来自受控响应，不冒充真实模型教学成品；真实回答在下方。DOCX容器和文字已核对，未在Microsoft Word做视觉验收。本轮没有测全软件总内存、长视频速度或实际安卓设备。</p>
<p>完全退出旧源码版后，双击<a href="../../验收最新版.vbs">验收最新版</a>。在原项目资料快选中引用已有成果即可，无须新开关；不想用的成果照常取消引用。手机同用电脑服务，公开页面壳更新至v46；已安装旧版不会因源码改动自动更新。</p></details>
<section class="prompt"><h2>成果“资料依据”的身份显示</h2><p>这里直接使用软件与手机共用的显示组件，数据来自上述受控生成记录和普通导入对照；只作身份显示演示，不触发读取或生成。</p><div id="sourceIdentityPreview"></div></section>'''
    evidence=evidence.replace('__COUNT__',str(len(tests)))
    page=re.sub(r'<header>.*?</header>',lambda _:intro,TEMPLATE,flags=re.S)
    page=page.replace('<main>','<main>'+evidence,1).replace('<title>StudyForge · 讲解质量真实对照</title>','<title>所选资料身份与来源表述实际对照 · StudyForge</title>')
    page=page.replace('grid-template-columns:repeat(3,minmax(0,1fr))','grid-template-columns:repeat(2,minmax(0,1fr))')
    page=page.replace('</style>',(ROOT/'web/source_evidence.css').read_text(encoding='utf-8')+'.report-table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d8e2df;padding:10px;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}pre{word-break:break-word}</style>',1)
    page=page.replace('查看本次提供的完整合成原资料','查看本组完整合成资料及已知身份').replace('核对实际请求、用量与原文指纹','核对公开请求、用量与回答指纹')
    page=page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。','回答、渲染器与字体均嵌入此页，切换不发送模型请求。身份区分不是正确性保证；原样回答及人工评价都可能需要进一步核对。')
    css=(ROOT/'web/vendor/katex.css').read_text(encoding='utf-8')
    css=re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((ROOT/'web/vendor/fonts'/m[1]).read_bytes()).decode()+')',css)
    css=re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
    data={'groups':groups,'count':8,'failures':[]}
    page=page.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',json.dumps(data,ensure_ascii=False).replace('<','\\u003c'))
    page=page.replace('__LIBRARIES__','\n'.join(inline_script((ROOT/'web/vendor'/n).read_text(encoding='utf-8')) for n in ['marked.js','purify.js','katex.js']))
    page=page.replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    preview={'source_reading':flow['source_reading']+next(c['read_manifests'] for c in cases if c['name']=='plain')}
    preview_js=(ROOT/'web/source_evidence.js').read_text(encoding='utf-8')+'\ndocument.getElementById("sourceIdentityPreview").append(studyforgeSourceEvidence.create('+json.dumps(preview,ensure_ascii=False).replace('<','\\u003c')+',"origin-report"));'
    body,closing,tail=page.rpartition('</body>');assert closing
    page=body+'<script>'+inline_script(preview_js)+'</script>'+closing+tail
    target=OUT/'所选资料身份与来源表述实际对照.html';target.write_text(page,encoding='utf-8')
    manifest={'date':'2026-10-16','answers':8,'groups':4,'real_model_requests':8,'program_checks':len(tests),
        'report_table_rows':[4],'source_identity_preview':True,'current_input_alignment':alignment,'workflow':flow,'package_created':False,'output_sha256':sha(target)}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(target),'answers':8,'program_checks':len(tests)},ensure_ascii=True))


if __name__=='__main__':main()
