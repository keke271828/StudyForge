"""Offline, auditable note-input fix with real outputs and native UI evidence."""
import base64
import copy
import hashlib
from html import escape
import json
from pathlib import Path
import re
import shutil
from xml.etree import ElementTree as ET

from scripts.build_teaching_comparison import TEMPLATE,inline_script

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/reading-note-acceptance-20261021'
TITLE='通读笔记对应与讲解实际验收'
NOTES={
 'cauchy':[
  '主证明、单点反例和A=0退化情形基本完整，数值可直接核对；没有因配错笔记而直接否定平方和恒非负。但开头纠正了学生并未声称的“A、B、C是解出来的”，回应稍偏；配方、判别式和总结仍多次重复同一主线。原稿保留，不作正确性认证。',
  '开头直接保留“取t=1并没有错”，再解释信息不足；顶点数例与一般配方衔接较清楚，A=0也保留。本次2680字符、57.13秒，比旧版短且快；仍重复展开配方和判别式。用同一个f记号表示不来自平方和的假想二次函数容易混淆，虽随后解释了区别，宜另起记号。不能据此认定所有证明更好。'],
 'gauss':[
  '净通量、法向符号和长方体E0A-E0A=0的计算清楚，没有把空腔零场结论套成一般结论。但重复较多，且总结把导体空腔一组充分条件写得像推出零场所必需的指定条件；引文中的公式也不是提供文本的逐字原样。',
  '同样讲清了有符号通量与点上的场，具体计算完整。本次2995字符、52.76秒，略短但更慢。仍主动扩展了空腔与无穷远条件；“所讨论区域无电荷且无穷远趋零便唯一零场”漏交代整个空间、无奇点及静电条件等范围，不能对任意外部源区域这样说。引文也改写了原文公式。输入对应修复没有消除这些内容问题。'],
}


def verify_request(messages,trace):
    from studyforge.dialogue_scope import CONTEXT_BOUNDARY
    from studyforge.deepseek_protocol import thinking_parameters
    body=copy.deepcopy(messages);body[0]['content']+=CONTEXT_BOUNDARY
    packet={'model':'deepseek-flash','messages':body,'stream':True,**thinking_parameters('high'),
            'stream_options':{'include_usage':True}}
    assert hashlib.sha256(json.dumps(packet,sort_keys=True,ensure_ascii=False).encode()).hexdigest()==trace['body_sha256']


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    folder=ROOT/'build/reading-note-real-20261021-1'
    packet=json.loads((folder/'inputs.json').read_text(encoding='utf-8'))
    results=json.loads((folder/'results.json').read_text(encoding='utf-8'))
    assert len(results)==4 and all(r['status']=='completed' and r['model_requests']==1 for r in results)
    groups=[];table=[];matched=0
    for case in packet['cases']:
        baseline,new=(case['requests'][arm] for arm in ('baseline','candidate'))
        assert baseline[0]==new[0]
        def unchanged(message):
            before,_,rest=message.partition('已完成的阅读笔记（辅助理解）：')
            _,sep,after=rest.partition('所选资料内容：')
            assert sep
            return before,after
        assert unchanged(baseline[1]['content'])==unchanged(new[1]['content'])
        assert case['receipt']['included'][0]['reading_part']==2
        reading=json.loads((folder/(case['id']+'-reading.json')).read_text(encoding='utf-8'))
        for request,trace in zip(reading['requests'],reading['http_attempts']):
            verify_request([{'role':'system','content':request['system']},{'role':'user','content':request['user']}],trace);matched+=1
        rows=[];arms={r['arm']:r for r in results if r['case']==case['id']}
        for index,arm in enumerate(('baseline','candidate')):
            row=arms[arm];raw=(folder/row['answer_file']).read_bytes();text=raw.decode('utf-8').replace('\r\n','\n')
            assert hashlib.sha256(text.encode()).hexdigest()==row['answer_sha256']
            verify_request(case['requests'][arm],row['http_attempts'][0]);matched+=1
            rows.append({'case':case['id'],'arm':arm,'label':'旧版：按部分编号配笔记' if arm=='baseline' else '新版：按实际原文输入匹配',
                'text':raw.decode('utf-8'),'sha256':hashlib.sha256(raw).hexdigest(),'review':NOTES[case['id']][index],
                'seconds':round(row['seconds'],2),'input_chars':row['input_characters'],'output_chars':row['characters'],
                'response_model':row['http_attempts'][0]['returned_model'],'usage':[r['usage'] for r in row['http_attempts']],
                'request':{'public_messages':case['requests'][arm],'actual_http_body_sha256':row['http_attempts'][0]['body_sha256'],
                           'reading_notes':case['reading_notes'],'new_context_receipt':case['receipt'] if arm=='candidate' else None,
                           'scope':'real model, synthetic materials, no tools/history/independent review'}})
        groups.append({'round':'真实文字组件对照 · 仅切换阅读笔记对应方式','case':case['id'],'title':case['title'],
            'question':case['question'],'source':'甲资料：\n'+case['other']+'\n\n当前乙资料：\n'+case['original']+
            '\n\n场景：乙在通读时是第2部分，写作时移到第1部分。旧版误配甲笔记；新版匹配乙笔记。\n核对点：\n'+'\n'.join(case['checks']),'rows':rows})
        table.append('<tr><td>'+escape(case['title'])+'</td><td>'+f"{arms['baseline']['seconds']:.2f}秒／{arms['baseline']['characters']}字符"+
                     '</td><td>'+f"{arms['candidate']['seconds']:.2f}秒／{arms['candidate']['characters']}字符"+'</td></tr>')
    assert matched==8
    ui_dir=ROOT/'build/reading-note-ui-20261021-1'
    ui=json.loads((ui_dir/'reading-note-ui-report.json').read_text(encoding='utf-8'))
    native=json.loads((ui_dir/'native-results.json').read_text(encoding='utf-8'))
    assert ui['passed'] and native['passed'] and len(native['cases'])==3 and native['controlled_requests']==4
    assert [r['receipt']['reason'] for r in native['cases']]==['exact_original_input','legacy_unassigned','no_matching_original_input']
    for name in ('电脑通读笔记依据.png','手机通读笔记依据-390.png','手机通读笔记依据-320.png'):
        shutil.copyfile(ui_dir/name,OUT/name)
    tests=ET.parse(ROOT/'build/reading-note-final-regression-20261021.xml').getroot().findall('.//testcase')
    assert len(tests)==422 and all(t.find(k) is None for t in tests for k in ('failure','error','skipped'))
    intro='''<header><div class="eyebrow">STUDYFORGE · READING INPUTS · 2026-10-21</div>
<h1>让阅读笔记跟随真正读过的原文</h1><p>修复按“第几部分”猜配笔记的问题；完整原文、当前学习要求与原有审查继续保留。</p>
<p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../docs/通读笔记对应与讲解验收.md">验收记录</a>。本轮未打包。</p>
<div class="notice"><strong>已经采用：新笔记保存实际原文输入指纹，生成按完全相同的输入对应。</strong>
无法匹配时直接依据完整原文，旧笔记明确标为未确认分段的整体导航。这里有4份真实模型讲解与人工意见；合成材料只复现错配场景，不是整本书、视频、网页端或生产教学质量认证。</div></header>'''
    evidence='''<details class="prompt"><summary>查看修复、真实测试结论、两端界面与限制</summary>
<h2>修复了什么</h2><p>通读与讲解采用不同顺序或分段时，“通读第2部分”不一定等于“讲解第2部分”。原来用编号挑笔记，会把另一处内容写成“本部分相关阅读笔记”。新通读记录实际分段的SHA-256和字符数；生成只采用完全相同输入的对应笔记，保存实际对应与节选记录。</p>
<p>无法匹配的新版笔记不猜配，讲解仍读取当前完整原文。旧笔记不删除、不强制重新通读、不事后补认；没有新版精确对应时，仅作为明确标注的整体导航。辅助输入最多3000字符，只保留完整段落，不从中间切断公式、代码或长段；没有可完整提供的段落时如实标注。</p>
<p>成果“资料依据”新增“通读笔记的使用范围”，桌面和手机共用，按需展开。这里的指纹只说明输入对应，不能证明笔记正确或原作者身份。此次未改共同教学提示词、模型、推理强度、详略和审查次数，也没有新增固定模型请求。</p>
<h2>真实模型结果：没有把输入修复夸成全面提升</h2><p>2组可复现合成材料，每组先实际通读甲、乙，再比较乙移到首位时的旧、新输入。共4次真实通读、4次真实讲解，均为deepseek-flash／high、直观与专业并存、深入学习、详略3；每次文字请求无工具、联网、聊天历史和独立核查。系统规则、原文和问题在每组内相同，只改变笔记分配及其对应说明。8份实际HTTP输入指纹逐一核对，原始输出及公开计数保留，未保存私有思考正文。</p>
<div class="report-table"><table><thead><tr><th>材料</th><th>旧配法</th><th>新配法</th></tr></thead><tbody>__ROWS__</tbody></table></div>
<p>柯西组新版开头较贴合学生原话，本次更短更快；两版仍重复配方与判别式。高斯组两版核心解释都清楚，新版本次更慢，仍有边界条件范围不完整和不必要扩展。公式改写也不能当作逐字引文。各视图下的人工评语具体指出这些不足，原样回答可下载。每臂仅一次，不给普遍质量分、不宣传整体提速。</p>
<p>真实阅读笔记也不是金标准：例如一份笔记把“导入文本”断言为“不是AI生成成果”，并无足够身份依据。新的对应记录不认证这些判断，也不把它们升级成原文。</p>
<h2>原生生成与两端检查</h2><p>422项相关检查通过，包括4项受控原生通读→串行／并行生成→原有快速核查→Word流程：输入相同时正确采用笔记，原文顺序及清单变化后不猜配，完整原文、原有请求数、快照和Word保留。另跑一套持久化原生流程，受控模型4次、外部请求0次，实际产生“对应／旧整体／不匹配”三份Word及记录。</p>
<p>实际Electron桌面和配对HTTPS手机页面验证三种记录区分、按需展开、刷新保留、390／320像素无页面横向溢出，手机下载实际Word成功，无新增模型请求或控制台错误。手机测试为真实移动页面的模拟宽度，不等于物理安卓设备验收。Word检查文件和内容，没有在Microsoft Word里验收分页与布局。</p>
<div class="shots"><figure><img src="电脑通读笔记依据.png" alt="实际桌面成果资料依据"><figcaption>实际桌面：对应关系在已有资料依据里展开</figcaption></figure><figure><img src="手机通读笔记依据-390.png" alt="实际配对HTTPS手机页面"><figcaption>配对HTTPS手机页面：不匹配时明确说明</figcaption></figure></div>
<p>旧安装EXE不包含本轮源码。双击顶部启动入口验收；没有自动改写既有成果。已有旧笔记不能还原当时的完整分段对应，资料重排或加入书库重点内容后可能不再匹配；这是保留完整原文继续写作的回退，不额外强制重读。本轮未验收长视频总耗时、全应用RAM或所有学科的教学质量。</p></details>'''
    page=re.sub(r'<header>.*?</header>',lambda _:intro,TEMPLATE,flags=re.S).replace('<main>','<main>'+evidence.replace('__ROWS__',''.join(table)),1)
    page=page.replace('<title>StudyForge · 讲解质量真实对照</title>',f'<title>{TITLE} · StudyForge</title>')
    page=page.replace('grid-template-columns:repeat(3,minmax(0,1fr))','grid-template-columns:repeat(2,minmax(0,1fr))')
    page=page.replace('</style>','.report-table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border:1px solid #d2e0d6;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}.lesson-math.display-math{display:block;overflow-x:auto;overflow-y:hidden;padding:6px 0}.katex-display{overflow:visible}.shots{display:flex;gap:14px;flex-wrap:wrap}.shots figure{margin:0;flex:1 1 280px;min-width:0}.shots img{max-width:100%;height:auto;border:1px solid #bccdbf;border-radius:12px}</style>',1)
    css=(ROOT/'web/vendor/katex.css').read_text(encoding='utf-8')
    css=re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((ROOT/'web/vendor/fonts'/m[1]).read_bytes()).decode()+')',css)
    css=re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
    page=page.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',json.dumps({'groups':groups,'count':4,'failures':[]},ensure_ascii=False).replace('<','\\u003c'))
    page=page.replace('__LIBRARIES__','\n'.join(inline_script((ROOT/'web/vendor'/n).read_text(encoding='utf-8')) for n in ('marked.js','purify.js','katex.js')))
    page=page.replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    target=OUT/(TITLE+'.html');target.write_text(page,encoding='utf-8')
    manifest={'answers':4,'groups':2,'report_table_rows':[2],'program_checks':422,'request_fingerprints_matched':matched,
        'real_model_requests':8,'reading_requests':4,'lecture_requests':4,'controlled_ui_requests':4,'ui_checks':len(ui['checks']),
        'reading_input_fix_adopted':True,'package_created':False,'output_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'path':str(target),**manifest},ensure_ascii=True))


if __name__=='__main__':main()
