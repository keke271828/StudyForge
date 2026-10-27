"""Build an offline reference-follow-up acceptance page; no model requests."""
import base64
import hashlib
from html import escape
import json
from pathlib import Path
import re
import shutil
from xml.etree import ElementTree as ET

from scripts.build_teaching_comparison import TEMPLATE,inline_script

ROOT=Path(__file__).resolve().parents[1]
PROBE=ROOT/'build/message-focus-real-20261016-1'
UI=ROOT/'build/message-focus-ui-20261016-2'
OUT=ROOT/'build/message-focus-acceptance-20261016'
NOTES={
 'epsilon':[
  '这次主要解释了最近一条回答的最大门槛，论证本身基本正确；问题没有明确指代，所以不能把这一合理猜测一概判错。但没有解答本次实际想问的任意ε与实例化。',
  '准确对准所选句，说明全称命题可以使用合法正数特例，也区分“取特例”和“仅证明一个值”。半径边界与开区间说明正确。不过后半又完整重证矛盾，1413字符偏长，没有完全遵守只讲这一处的要求；本次也稍慢。'],
 'python':[
  '原代码对象关系与[[7],[0,8]]静态结果正确，未把后来的append对照当原代码；表格很清楚，但重复说明和总结较多。没有引用时这次也理解了所问对象关系。',
  '明确解释下标赋值替换槽位、append修改旧对象，原结果正确且较短。本次更快，但不能把单次服务时间当普遍提速；“等号创建对象”最好明确为右边列表表达式创建新对象，“运行完后的静态结果”可更明确写成静态推演。'],
 'energy':[
  '正确更正旧回答理由，保留正确偏导，由链式法则和运动方程得到守恒；没有扩展外力模型。结尾再次重复，“形式条件之一”需结合模型语境理解，不能扩张成一般必要条件。',
  '准确指定旧回答第一句有误，保留正确偏导，写出dE/dt=v(kx+mv′)并使用运动方程；没有新增外力模型。两版均已抓住问题，不支持“全面提升”结论。仍有重复代入；“这些条件才保证”容易夸成每项都必要；原文转换为公式排版的引文已不再逐字一致。'],
}


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
 OUT.mkdir(parents=True,exist_ok=True)
 packet=load(PROBE/'cases.json');results=load(PROBE/'results.json');ui=load(UI/'ui-results.json')
 assert len(results)==6 and all(r['status']=='completed' and r['model_requests']==1 for r in results)
 assert ui['passed'] and len(ui['checks'])==5 and ui['external_model_requests']==0
 groups=[];table=[]
 for case in packet['cases']:
  by_arm={r['arm']:r for r in results if r['case']==case['id']};rows=[]
  for index,(arm,label) in enumerate([('baseline','同样问题 · 未附明确引用'),('reference','同样问题 · 附用户选中的原句')]):
   row=by_arm[arm];path=PROBE/row['answer_file'];answer=path.read_text(encoding='utf-8')
   rows.append({'case':case['id'],'arm':arm,'label':label,'text':answer,'review':NOTES[case['id']][index],
    'seconds':round(row['seconds'],2),'input_chars':sum(len(m['content']) for m in case['requests'][arm]),
    'output_chars':len(answer),'response_model':'deepseek-flash','usage':[t['usage'] for t in row['http_attempts']],
    'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'request':case['requests'][arm]})
  a,b=by_arm['baseline'],by_arm['reference']
  table.append('<tr><td>'+escape(case['title'])+'</td><td>'+f"{a['seconds']:.2f}秒／{a['output_characters']}字符"+'</td><td>'+f"{b['seconds']:.2f}秒／{b['output_characters']}字符"+'</td></tr>')
  context=case['source']+'\n\n此前AI回答（可能有误）：\n'+case['target']+'\n\n后来的AI回答：\n'+case['later']+'\n\n用户明确选中的原句：\n'+case['quote']+'\n\n人工核对点：\n'+'\n'.join(case['checks'])
  groups.append({'round':'导师实际入口' if case['role']=='tutor' else '文档实际输入构造','case':case['id'],'title':case['title'],'question':case['question'],'source':context,'rows':rows})
 tests=set();suites={}
 for filename in ('message-focus-final-regression-20261016.xml','message-focus-delivery-regression-20261016.xml'):
  rows=ET.parse(ROOT/'build'/filename).getroot().findall('.//testcase')
  assert rows and all(r.find(k) is None for r in rows for k in ('failure','error','skipped'))
  suites[filename]=len(rows);tests.update((r.get('classname'),r.get('name')) for r in rows)
 for filename in ('电脑端原句追问.png','手机端原句选择.png','手机端原句追问.png'):shutil.copyfile(UI/filename,OUT/filename)
 intro='''<header><div class="eyebrow">STUDYFORGE · PRECISE FOLLOW-UP · 2026-10-16</div><h1>选中一句，接着把真正的卡点讲清</h1><p>电脑和手机的原句追问，3组6份真实回答。<a href="../../验收最新版.vbs">源码验收入口</a> · <a href="../../docs/导师原句追问与连接释放验收.md">验收记录</a>。本轮未打包。</p><div class="notice">同模型、推理强度与教学规则，只增加用户明确选择的引用信息。这不是模型能力盲评：没选原句的指代可能含糊，回答最近一步也可能是合理理解。引用帮助对准目标，仍不保证简洁或每个额外判断正确。全部原样保留。</div></header>'''
 evidence='''<details class="prompt" open><summary>新增入口、检验与使用方法</summary><h2>怎样使用</h2><ol><li>在已完成的导师回答下点击“针对这段追问”。</li><li>查看原文、翻段或跳到后半部分；选取1–3000字符。7000字符以内的短回答也能整条引用。</li><li>点击“使用选中原句”，再在原输入框写你的疑问并发送。选择原句不调用AI、不解析文件；不会自动生成新任务。</li><li>引用草稿按项目与对话分别保存，重开仍可继续。发送后问题旁保留可展开的原句，后续对话与文档生成均可恢复这处指向。</li></ol><p>引用绑定项目、对话、已保存回答、内容指纹和Unicode坐标，重复句子与换行精确核对。旧回答已变化时重新选段，不静默替换。学生问题正文保持原样，引用另表保存；旧AI内容不是学生作答、原文件证据或新授权。画像只用选中原句定位知识，不能把旧AI判断当作学生理解。</p>
<h2>实际回答观察</h2><p>3题在采样前固定；DeepSeek Flash／high，工具和联网关闭，合成来源、历史和疑问。两份真实导师输入及一份文档输入各两版，只测首次文字输出；每臂一次、没有盲评与重复抽样，不含扫描书、视频或额外文档审核。极限样例中原回答转向最近的最大门槛，引用后准确回答任意ε；但新回答又完整重证，仍偏长。编程两版均正确，引用版较短；能量文档两版均改正了错误理由，条件和引文措辞仍有不足。</p><div class="report-table"><table><thead><tr><th>问题</th><th>未附引用</th><th>附明确原句</th></tr></thead><tbody>__ROWS__</tbody></table></div><p>准确性与简洁性仍需分别评估，不能把更快的一次或引用功能通过当成所有讲解质量提升。当前共同教学规则没有因为这次试验加长。</p>
<h2>修复聊天连接释放</h2><p>先复现正常完成、模型报错、停止和准备失败时未关闭当前客户端的缺口，再补上每次聊天自有连接的清理；关闭失败不覆盖原问题。实际DeepSeek客户端与受控HTTP传输确认底层客户端已关闭。原对话消息与按对话保存的内部状态保持，不把关闭一次HTTP连接等同清空聊天。</p><p>这修复了资源生命周期，没有测出整软件总RAM下降比例；也不承诺云端生成速度普遍提高。已开始的文档仍使用自己的连接和任务上下文。</p>
<h2>程序和两端交互</h2><p>__CHECKS__项最终相关去重程序检查通过，覆盖原句、长窗口、坐标、内容变化、项目／对话隔离、历史分页、冻结文档上下文、原文完整性、画像证据、模型与权限、作业答案隔离、项目清理、手机与指南，以及聊天完成／失败／取消的连接关闭。</p><p>5项实际Electron电脑／配对HTTPS手机尺寸交互通过：长回答后半段、Unicode与CRLF原句；换对话和重开草稿；发送与已存历史；手机原句弹窗和引用；不因引用产生掌握分或画像判断。2次受控模型请求，0次外部AI调用。没有重新验收真实安卓设备或所有第三方模型账号。指南与手机缓存v50同步，源码未打包。</p><details><summary>查看电脑和手机截图</summary><p><img src="电脑端原句追问.png" alt="电脑端原句追问" style="max-width:100%"></p><p><img src="手机端原句选择.png" alt="手机选取AI原句" style="max-width:390px;width:100%"></p><p><img src="手机端原句追问.png" alt="手机追问历史" style="max-width:390px;width:100%"></p></details><p>完全退出旧源码版后，双击<a href="../../验收最新版.vbs">验收最新版</a>。聊天记录仍在原本机数据目录中。本轮实验使用隔离数据和合成材料，未改动用户资料、画像或模型设置。</p></details>'''
 evidence=evidence.replace('__ROWS__',''.join(table)).replace('__CHECKS__',str(len(tests)))
 page=re.sub(r'<header>.*?</header>',lambda _:intro,TEMPLATE,flags=re.S).replace('<main>','<main>'+evidence,1)
 page=page.replace('<title>StudyForge · 讲解质量真实对照</title>','<title>导师原句追问实际对照 · StudyForge</title>')
 page=page.replace('grid-template-columns:repeat(3,minmax(0,1fr))','grid-template-columns:repeat(2,minmax(0,1fr))')
 page=page.replace('</style>','.report-table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border:1px solid #d2e0d6;text-align:left}a{color:#236b5b;overflow-wrap:anywhere}.prompt{overflow-wrap:anywhere}.lesson-math.display-math{display:block;overflow-x:auto;overflow-y:hidden;padding:6px 0}.katex-display{overflow:visible}</style>',1)
 css=(ROOT/'web/vendor/katex.css').read_text(encoding='utf-8')
 css=re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((ROOT/'web/vendor/fonts'/m[1]).read_bytes()).decode()+')',css)
 css=re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
 page=page.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',json.dumps({'groups':groups,'count':6,'failures':[]},ensure_ascii=False).replace('<','\\u003c'))
 page=page.replace('__LIBRARIES__','\n'.join(inline_script((ROOT/'web/vendor'/n).read_text(encoding='utf-8')) for n in ('marked.js','purify.js','katex.js'))).replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
 page=page.replace('查看本次提供的完整合成原资料','查看合成资料、此前回答和所选原句')
 page=page.replace('所有数据与字体已嵌入此文件；阅读、切换与下载不发送模型请求。修订前有缺陷的回答保留用于对照，切勿把它们当作定稿教材。','完整回答、公开输入、公式渲染与字体已嵌入本页；切换不发送请求。实验输出含残余问题，不作为定稿教材。')
 target=OUT/'导师原句追问实际对照.html';target.write_text(page,encoding='utf-8')
 (OUT/'manifest.json').write_text(json.dumps({'answers':6,'groups':3,'report_table_rows':[3],'program_checks':len(tests),'suites':suites,'ui_checks':5,'real_model_requests':6,'package_created':False,'output_sha256':hashlib.sha256(target.read_bytes()).hexdigest()},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'path':str(target),'checks':len(tests),'suites':suites},ensure_ascii=True))


if __name__=='__main__':main()
