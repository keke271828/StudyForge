"""Raw six-pair teaching comparison and exact-answer local export acceptance."""
import base64
from datetime import datetime
from html import escape as esc
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from xml.etree import ElementTree

from scripts.build_teaching_comparison import TEMPLATE,inline_script

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/answer-save-acceptance-20261016'
PROBE=ROOT/'build/compact-teaching-real-20261016-1'
UI=ROOT/'build/message-exports-ui-20261016-2'
NOTES={
 'epsilon_followup':{
    'baseline':'正确区分“使用全称假设的特例”与“只证一个特例来建立全称命题”，没有重讲整段几何证明；解释仍有重复。',
    'compact':'主要量词逻辑讲清，但“消费假设”不够自然，又将削弱假设泛称为逻辑不合法；从较强假设推出较弱结论本可合法，需要区分使用推论与重新定义极限。比原版更长、更慢。'},
 'gauss_followup':{
    'baseline':'六面通量算例和“平均法向分量为零”有帮助；但“只有法向分量处处相同才能……”应理解为直接使用常数积分规则的条件，不能泛化成积分等式的必要条件。未充分讲清匀强矢量本可提出积分。',
    'compact':'找到了漏掉方向的关键，也给出六面计算；但“根本没有可以提出来的公共因子E”过强。匀强场的E₀可以提成E₀(A−A)=0；不能把剩余有向面积和换成6A，或从恒等式0=0解出E₀。更短但更慢，未采纳。'},
 'social_explanation':{
    'baseline':'例子中的截止规则、习惯、时间与目标围绕同一件写周报事件，改正了此前例子换问题的风险；“说得通的机制”仍不等于已证明真实原因，示意与证据需区分。',
    'compact':'到岗事件的几种因素有具体联系，但“唯一解释必须没有制度就不会发生”混入必要条件判断；总结的“通常／往往”也超出这段材料可支持的经验范围。更长、更慢，无稳定优势。'},
 'code_copy':{
    'baseline':'外层分开、内层共享及两次修改的对象讲清，最终列表正确；表格与总结有一定重复。属于静态推演，没有把它冒充实际执行结果。',
    'compact':'同样正确推演对象与引用，表格和接回原操作较清楚；这次略短且约快5秒，但仍较长。此例可供阅读，不能据此推广为候选全面更好。'},
 'cauchy_direction':{
    'baseline':'准确计算点积与45°夹角，保留0°端点，不把正点积等同于同向。主要目标回答完整，仍有重复。',
    'compact':'主要判断与数值也正确，包含零角、锐角和正等号的区分；追加柯西取等条件，篇幅更长。本例没有重现上一轮候选的同向错误，也没有稳定优于原版。'},
 'necessary_condition':{
    'baseline':'识别b>0和ab≥1已推出a>0，给出合法推导，区分这组充分条件与结论的一般必要条件。篇幅偏长，但未给违反剩余条件的假反例。',
    'compact':'同样识别冗余条件，AM-GM与另一种推导都成立；速度较快，但更长且重复两种写法，不支持“提示短就回答更精炼”。'},
}


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=True,parents=True);packet=load(PROBE/'cases.json');results=load(PROBE/'results.json')
    assert len(results)==12 and all(r['status']=='completed' and r['model_requests']==1 for r in results)
    groups=[];table=[]
    for case in packet['cases']:
        name=case['id'];pair={r['arm']:r for r in results if r['case']==name};rows=[]
        for arm,label in [('baseline','现有共同教学规则'),('compact','紧凑候选 · 未集成')]:
            r=pair[arm];f=PROBE/r['answer_file'];text=f.read_text(encoding='utf-8')
            rows.append({'case':name,'arm':arm,'label':label,'text':text,'review':NOTES[name][arm],
                'seconds':round(r['seconds'],2),'input_chars':r['input_characters'],'output_chars':len(text),'sha256':sha(f),
                'response_model':'deepseek-flash','usage':[t['usage'] for t in r['http_attempts']],'request':case['requests'][arm]})
        a,b=pair['baseline'],pair['compact']
        table.append('<tr><td>'+esc(case['title'])+'</td><td>'+f"{a['seconds']:.2f}秒 / {a['output_characters']}字符"+'</td><td>'+f"{b['seconds']:.2f}秒 / {b['output_characters']}字符"+'</td></tr>')
        history='\n\n'.join('已有公开讲解（合成背景）：\n'+m['content'] for m in case.get('history',[]))
        groups.append({'round':'导师实际入口' if case['role']=='tutor' else '文档实际提示构造','case':name,'title':case['title'],
            'question':case['question'],'source':case['source']+'\n\n'+history+'\n\n人工核对点：\n'+'\n'.join(case['checks']),'rows':rows})
    checks=ElementTree.parse(ROOT/'build/message-export-final-regression-20261016.xml').getroot().findall('.//testcase')
    assert checks and len({(c.get('classname'),c.get('name')) for c in checks})==len(checks)
    assert not any(c.find(k) is not None for c in checks for k in ('failure','error','skipped'))
    ui=load(UI/'ui-report.json');assert ui['passed'] and len(ui['checks'])==5 and not ui['model_requests']
    db=sqlite3.connect(str(UI/'data/studyforge.sqlite3'));db.row_factory=sqlite3.Row
    outputs=[]
    for key,name in [('word_artifact','实际导师回答直接保存.docx'),('markdown_artifact','实际导师回答直接保存.md')]:
        row=dict(db.execute('SELECT * FROM artifacts WHERE id=?',(ui[key]['id'],)).fetchone())
        job=db.execute('SELECT created_at,updated_at FROM jobs WHERE id=?',(ui[key]['metadata']['reexport_job_id'],)).fetchone()
        elapsed=(datetime.fromisoformat(job['updated_at'])-datetime.fromisoformat(job['created_at'])).total_seconds()
        shutil.copyfile(row['path'],OUT/name);outputs.append({'file':name,'seconds':elapsed,'sha256':sha(OUT/name)})
    for source,name in [('电脑端保存回答.png','电脑端保存回答.png'),('手机端保存回答320.png','手机端保存回答320.png')]:shutil.copyfile(UI/source,OUT/name)
    db.close()
    intro='''<header><div class="eyebrow">STUDYFORGE · TEACHING &amp; ANSWER SAVE · 2026-10-16</div><h1>先把问题讲清，再把满意的回答留下</h1>
<p>6组、12份真实回答。<a href="../../验收最新版.vbs">源码验收入口</a> · <a href="../../web/help/guide.html#outputs">软件内指南</a>。本轮未打包。</p>
<div class="notice">这轮简短提示候选没有稳定优势，仍有物理与概念措辞问题，未替换生产教学规则。新增的是回答底部“保存为成果”：直接排版已公开的完整导师回答，保留这版内容，零新增模型请求；保存不等于重新核查过内容。</div></header>'''
    evidence='''<details class="prompt"><summary>对照结论、功能用法与检验范围</summary><h2>提示词实验</h2><p>同一DeepSeek Flash／high，每臂一次，共12次真实请求，工具与联网关闭。导师组先从实际聊天入口捕获已有公开背景、当前问题和所选文件，文档组使用实际讲解函数；每组仅替换共同教学规则，保留其余模式、风格、语言、来源与学生要求。客户端既有边界规则照常附加。所有材料与此前讲解背景均为合成测试，不包含你的真实对话。</p>
<p>候选每组少324个输入字符，但4组更慢、2组更快，输出也没有稳定变短。没有重复或盲评，不能把单次差异归因于单一句子或推广成能力排名；实际输出及人工批评在下方。</p>
<div class="report-table"><table><thead><tr><th>主题</th><th>现有规则：耗时／正文</th><th>紧凑候选：耗时／正文</th></tr></thead><tbody>'''+''.join(table)+'''</tbody></table></div>
<p>当前规则保留。高斯题两版都仍有把积分改写条件说得过强的风险，简化不是可靠修复。把场强常数提出积分，与把有向面积和错误地换成总面积，是两件事；报告没有润色这些回答来伪装成模型已改正。</p>
<h2>新增：保存这条回答</h2><ol><li>等导师回答完成并进入聊天历史，点击底部“保存为成果”。用户发言、空白及已停止的半成品不提供此入口。</li><li>填写名称，选择Word、PDF、PPT、FreeMind、Markdown或文本；取消窗口不会创建任务。</li><li>后台本机排版，可在任务区暂停、继续或取消。新文件归原项目、标明原对话，并进入资料快选供手动引用。</li></ol>
<p>不重新读取后来选的资料，不重写讲解、不追加问卷或习题、不重复插入聊天，不记成新的掌握证据。保存时按内容指纹固定版本；旧回答的模型和完整资料范围未被单独记录时如实显示未知，不用当前设置补填。要继续改写或核查，请先在对话中得到新的完整回答，再保存那条。</p>
<p>实际桌面把本轮2045字符的Python浅复制回答保存为Word，配对HTTPS手机再保存为Markdown。Word任务从入队到完成约__WORD_SECONDS__秒，Markdown约__MD_SECONDS__秒，均0次模型请求。这只是本机保存现成回答，不能当作首次讲解、视频或扫描书提速。</p>
<p><a href="实际导师回答直接保存.docx">下载实际保存的Word</a> · <a href="实际导师回答直接保存.md">下载原样Markdown</a>。Word容器和列表结果核对通过，Markdown下载字节指纹与原回答一致；未在Microsoft Word作视觉验收，其他格式受各自导出器支持范围限制。</p>
<h2>验收</h2><p>__COUNT__项相关去重回归通过，覆盖六种实际格式、版本与项目／对话归属、重复请求、停止回答、暂停／续接／重启、原成果换格式、手机路由和既有对话恢复。实际Electron桌面与配对HTTPS手机5项交互通过，320像素暗色选择窗口无横向溢出，保存过程零外部模型请求，未测真实安卓设备或全软件总内存。</p>
<details><summary>查看保存窗口截图</summary><p><img src="电脑端保存回答.png" alt="电脑端保存回答窗口" style="max-width:100%"></p><p><img src="手机端保存回答320.png" alt="320像素手机保存窗口" style="max-width:320px;width:100%"></p></details>
<p>完全退出旧源码版后，双击<a href="../../验收最新版.vbs">验收最新版</a>。手机刷新使用同一电脑服务，公开页面壳更新至v47；已有安装包不会自动改变。</p></details>'''
    evidence=evidence.replace('__COUNT__',str(len(checks))).replace('__WORD_SECONDS__',f"{outputs[0]['seconds']:.2f}").replace('__MD_SECONDS__',f"{outputs[1]['seconds']:.2f}")
    page=re.sub(r'<header>.*?</header>',lambda _:intro,TEMPLATE,flags=re.S).replace('<main>','<main>'+evidence,1)
    page=page.replace('<title>StudyForge · 讲解质量真实对照</title>','<title>教学聚焦对照与满意回答保存 · StudyForge</title>')
    page=page.replace('grid-template-columns:repeat(3,minmax(0,1fr))','grid-template-columns:repeat(2,minmax(0,1fr))')
    page=page.replace('</style>','.report-table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d8e2df;padding:10px;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}pre{word-break:break-word}</style>',1)
    page=page.replace('查看本次提供的完整合成原资料','查看合成材料、已有讲解与核对点').replace('核对实际请求、用量与原文指纹','核对公开输入、用量与回答指纹')
    page=page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。','十二份原样回答、渲染器与字体嵌入此页；切换不请求模型。候选未集成，现有规则也仍会有错误；人工评价同样欢迎核对。')
    css=(ROOT/'web/vendor/katex.css').read_text(encoding='utf-8')
    css=re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((ROOT/'web/vendor/fonts'/m[1]).read_bytes()).decode()+')',css)
    css=re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
    page=page.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',json.dumps({'groups':groups,'count':12,'failures':[]},ensure_ascii=False).replace('<','\\u003c'))
    page=page.replace('__LIBRARIES__','\n'.join(inline_script((ROOT/'web/vendor'/n).read_text(encoding='utf-8')) for n in ['marked.js','purify.js','katex.js']))
    page=page.replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    target=OUT/'教学聚焦对照与满意回答保存.html';target.write_text(page,encoding='utf-8')
    manifest={'answers':12,'groups':6,'report_table_rows':[6],'program_checks':len(checks),'real_model_requests':12,
        'candidate_adopted':False,'ui_checks':5,'save_model_requests':0,'outputs':outputs,'package_created':False,'output_sha256':sha(target)}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(target),'program_checks':len(checks),'candidate_adopted':False},ensure_ascii=True))


if __name__=='__main__':main()
