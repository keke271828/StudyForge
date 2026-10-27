"""Publish public exercises and real validation evidence, never private solutions."""
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
from urllib.parse import quote,unquote,urlsplit

from docx import Document

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/repair-selection-acceptance-20261022'
GATE=ROOT/'build/repair-selection-final-20261022'
UI=ROOT/'build/repair-selection-ui-20261022-1'
LIVE=ROOT/'build/repair-selection-live-20261022-1'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    gate=json.loads((GATE/'command.json').read_text(encoding='utf-8'))
    ui=json.loads((UI/'ui-report.json').read_text(encoding='utf-8'))
    live=json.loads((LIVE/'report.json').read_text(encoding='utf-8'))
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed'] and live['status']=='completed'
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert all(sha(ROOT/name)==digest for name,digest in gate['production_after'].items())
    student=json.loads((LIVE/'student-worksheet.json').read_text(encoding='utf-8'))
    assert len(student['questions'])==1 and student['repair']['targets'][0]['index']==0 and not student.get('solutions')
    word=Path(live['word_file']);assert word.is_file()
    body_text='\n'.join(paragraph.text for paragraph in Document(word).paragraphs)
    assert student['questions'][0]['question'] in body_text and '参考解析' not in body_text and 'PRIVATE_' not in body_text
    OUT.mkdir(exist_ok=True)
    def href(path):return quote(os.path.relpath(path,OUT).replace('\\','/'),safe='/')
    def link(path,label):return '<a href="'+href(path)+'">'+escape(label)+'</a>'
    def image(filename,label):
        path=UI/filename;assert path.is_file()
        return '<figure><a href="'+href(path)+'"><img src="'+href(path)+'" alt="'+escape(label)+'"></a><figcaption>'+escape(label)+'</figcaption></figure>'
    n=gate['tests']['total'];q=escape(student['questions'][0]['question'])
    total_tokens=sum(call.get('usage',{}).get('total_tokens',0) for call in live['calls'])
    model_seconds=sum(call['seconds'] for call in live['calls'])
    names=['设计一题','独立解题','解析核查','成品核查']
    timing=''.join('<tr><td>'+names[index]+'</td><td>'+str(call['seconds'])+'秒</td><td>'+str(call.get('usage',{}).get('total_tokens','未提供'))+'</td></tr>' for index,call in enumerate(live['calls']))
    checks=''.join('<li>'+escape(text)+'</li>' for text in ui['checks'])
    sources=[GATE/'command.json',GATE/'regression.xml',GATE/'regression.log',UI/'ui-report.json',LIVE/'report.json',LIVE/'student-worksheet.json',word]
    evidence=''.join('<li>'+link(path,path.name)+'</li>' for path in sources)
    manual={'scope':'one_synthetic_case_not_general_quality_certification',
        'target':'只选择原第1题高斯定律；未生成原第2题算术卡点的练习',
        'strengths':['新题由一般判断转为等量异号点电荷情境，并要求理由或图像；不是只替换数值',
                     '独立解答与设计解答之间未发现主结论冲突；公共Word没有参考解与私有检查说明'],
        'limitations':['题干应明确两点电荷位于不同位置，且讨论电场时排除理想点电荷所在位置；自动核查没有指出此点',
                       '点电荷场的基本性质属于额外前置，若学生尚未学到，需要题面补足或改用已给的均匀场情境',
                       '2/5是沿用的软件参考难度，不是经过实测校准的等难度证明'],
        'adoption':'原始题目和Word保留，不静默替换；本轮未据单一样例修改通用导师提示词'}
    (OUT/'人工核对说明.json').write_text(json.dumps(manual,ensure_ascii=False,indent=2),encoding='utf-8')
    styles='''*{box-sizing:border-box}html{background:#edf2ec;color:#253d34;font:16px/1.85 system-ui,"Microsoft YaHei",sans-serif}body{max-width:1120px;margin:auto;padding:28px}header,section{border:1px solid #d6e3d6;background:#fffefa;border-radius:22px;padding:26px 30px;margin-bottom:20px}header{background:linear-gradient(120deg,#fffefa,#dfede1)}h1{font-size:33px;line-height:1.5;margin:8px 0}h2{font-size:23px}h3{font-size:18px}.tag{font-size:12px;font-weight:700;letter-spacing:2px;color:#49765c}.stats{display:flex;flex-wrap:wrap;gap:14px}.stats div{padding:12px 20px;background:#fffefa;border:1px solid #c8ddcc;border-radius:14px}.stats strong{display:block;font-size:27px;color:#286548}a{color:#286548;text-underline-offset:4px}li{margin:9px 0}.notice{background:#fcf3e1;border-left:4px solid #bf8c39;border-radius:9px;padding:16px 18px}.good{background:#edf5ec;border-left:4px solid #4c8961;padding:15px 18px;border-radius:9px}blockquote{margin:18px 0;padding:18px 22px;border-left:4px solid #4c8961;background:#eff5eb;border-radius:10px;font-size:17px}table{width:100%;border-collapse:collapse;display:block;overflow:auto}th,td{border:1px solid #d8e4d9;padding:10px 13px;min-width:130px;text-align:left}th{background:#edf5ec}figure{margin:24px 0}img{display:block;width:100%;height:auto;border:1px solid #d4e1d6;border-radius:14px}figcaption,.small{font-size:13px;color:#56715f}.phones{display:grid;grid-template-columns:1fr 1fr;gap:24px;max-width:820px;margin:auto}.phones figure{min-width:0}.steps{display:flex;gap:10px;flex-wrap:wrap;padding:0;list-style:none}.steps li{padding:10px 14px;border:1px solid #d4e3d3;border-radius:13px;background:#f1f6ee}@media(max-width:650px){body{padding:12px}header,section{padding:18px;border-radius:16px}h1{font-size:25px}.phones{grid-template-columns:1fr;max-width:390px}.stats div{flex:1;min-width:120px}}'''
    page=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>按卡点选题与单题再练验收</title><style>{styles}</style></head><body>
<header><div class="tag">STUDYFORGE · 2026-10-22 · 源码验收</div><h1>只练当前卡点，也能组合自己的再练范围</h1><p>读完一道题的补讲，主动选择这处卡点生成一题；需要更多练习时，再组合其他失分项。范围不同，题单各自保存。</p><div class="stats"><div><strong>{n}</strong>关联回归通过</div><div><strong>{len(ui['checks'])}</strong>实际两端界面检查</div><div><strong>{live['model_requests']}</strong>真实模型请求</div></div></header>
<section><h2>怎样体验</h2><ol><li>从系统托盘退出旧版 StudyForge，双击 {link(ROOT/'验收最新版.vbs','验收最新版.vbs')}。手机连接该实例后刷新，手机壳为v68。</li><li>在已有批改的普通作业中打开“按题回看”，选择有失分依据的题，点击“针对这道题再练”。选题窗口只预选这一题。</li><li>也可从原有“按本次错因同难度再练”入口打开窗口。这里默认全选失分项，可清空后自行勾选。</li><li>点击“生成选中的N道练习”才开始模型任务。新题单单独交付DOCX，完整提交前没有答案。</li></ol><ul class="steps"><li>回看原题与补讲</li><li>选择当前卡点</li><li>同参考难度的新情境</li><li>完整提交后再批改</li></ul><p>{link(ROOT/'web/help/guide.html','内置新手指南')}第10节已补充操作。本轮未打包EXE。</p></section>
<section><h2>切换范围有实际区别</h2><table><thead><tr><th>选择范围</th><th>实际题数</th><th>对应原题</th><th>再次请求</th></tr></thead><tbody><tr><td>只选第二处卡点</td><td>1题</td><td>原第2题</td><td>复用该题单</td></tr><tr><td>只选第一处卡点</td><td>1题</td><td>原第1题</td><td>独立保存</td></tr><tr><td>两处都选</td><td>2题</td><td>原第1、2题</td><td>与两个单题范围分开保存</td></tr></tbody></table><p>实际后台任务序列依次测试第二题、第一题、两题，再返回第二题；前三次各沿用原有四项模型步骤，共12项受控请求，返回第二题及手机再次请求第一题均不增加请求。清空选题后生成按钮禁用，不回退为整套。这里的模型返回是合成夹具，不用于评价教学质量。</p></section>
<section><h2>实际界面</h2>{image('desktop-selected-one.png','从按题回看进入，只预选原第2题；原第1题没有被选中')}{image('desktop-selected-all.png','从整套再练入口进入，自行组合失分项')}<div class="phones">{image('phone-select-390.png','已配对HTTPS手机界面的选题窗口')}{image('phone-select-320-dark.png','320px深色界面，勾选项与生成按钮可读')}</div></section>
<section><h2>真实 DeepSeek 单题试验</h2><p>模型为deepseek-flash，推理设置high。原作业及评分为合成数据，存在两处失分，本次只选择高斯定律。实际交付1题，目标保留为原第1题，未额外生成算术题。样例原样保留：</p><blockquote>{q}</blockquote><p>{link(word,'下载真实模型交付的单题DOCX · 无答案')} · {link(LIVE/'student-worksheet.json','查看公开题单记录')}</p><h3>人工核对</h3><div class="good">新题改变了具体情境，并要求说明理由或物理图像，能够围绕所选概念继续观察思路。独立解答与设计解答之间未发现主结论冲突；公共Word未包含私有参考解和评分标准。</div><div class="notice"><strong>仍有需要改进的内容。</strong>题干应明确两点电荷处于不同位置，并在讨论电场时排除理想点电荷所在位置；自动核查未指出这点。另外，若学生尚未学习点电荷场的基本性质，应在题面补足前置，或使用已讲过的均匀场情境。2/5只是软件参考难度，不是经实验校准的等难度证明。</div><p>原始题目与文件没有被静默改写。本轮不依据这一个样例调整通用导师提示词，也不把自动核查通过当作绝对正确。</p><p>{link(OUT/'人工核对说明.json','查看人工核对记录')}</p></section>
<section><h2>时间与请求数</h2><table><thead><tr><th>步骤</th><th>本次模型响应时间</th><th>总Token（含推理）</th></tr></thead><tbody>{timing}</tbody></table><p>总流程{live['seconds']}秒，四次模型响应累计约{model_seconds:.3f}秒，总Token为{total_tokens}。这是一个小材料、单题、high推理设置的试验；没有完整两题旧方案对照，不能据此声称普遍提速。此次主要减少不需要的题目，保留已有设计、独立解题和两项核查步骤，没有新增固定审查轮次。</p></section>
<section><h2>防止学习证据错位</h2><ul><li>错因问卷未完成、评分待核实或原有费曼流程尚未完成时，不借新入口绕过。</li><li>答对题不标成错误；原因未明时仅观察思路，学生自报继续标为未独立验证。</li><li>选题绑定这次提交及评分／补讲依据。依据改变时重新选题，不默默切到其他作答。</li><li>后台载入与恢复保留所选原题号；不同范围分别按依据保存、匹配复用。</li><li>缺少目标标记的旧缓存不会冒充有效定向题，会重新生成；原题单仍保留。</li><li>同一题单的并发重复提交在入队前再次检查；不同题单沿用原并发设置。</li><li>查看、勾选及生成再练不改原评分，不重复提交作业，不把看完补讲记作掌握。</li></ul></section>
<section><h2>完整验收证据</h2><p>{n}项关联回归全部通过，失败、错误、跳过均为0；15个生产文件测试前后指纹一致，另有7项Node语法检查。实际两端界面检查如下：</p><ol>{checks}</ol><p class="notice">界面使用隐藏Electron和已配对HTTPS网关，未替代实体安卓手机测试。受控界面使用12项模拟模型请求；另有上述4次真实模型请求，二者不混算。本轮没有完整软件内存、速度或跨学科教学质量的全面验收，也未认证Word的实际分页排版。</p><ul>{evidence}</ul><p>{link(ROOT/'docs/按卡点选题与单题再练验收.md','实现与验收说明')}</p></section></body></html>'''
    target=OUT/'按卡点选题与单题再练验收.html';target.write_text(page,encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({'gate':gate,'ui':ui,'live':live,'manual':manual,
        'public_files':{str(path.relative_to(ROOT)):sha(path) for path in sources}},ensure_ascii=False,indent=2),encoding='utf-8')
    doc=ROOT/'docs/按卡点选题与单题再练验收.md'
    doc.write_text(f'''# 按卡点选题与单题再练验收\n\n2026-10-22，源码更新，未打包EXE。\n\n## 实现\n\n- 修复练习支持显式选择原失分题号；默认全选，可从按题回看仅预选当前题。查看与勾选零模型请求，确认后才生成。\n- 每个所选卡点各出一道同参考难度新题，提交前隐藏答案；旧的整套接口与费曼／问卷／评分待核实边界保留。\n- 不同范围依照提交与上下文签名独立查找缓存，不被最后一个生成结果覆盖；缺少目标标记的缓存不复用。\n- 后台入队及恢复保留RepairIn选择与依据；同题单入队前二次检查占用，避免并发重复创建。\n- 选题窗口绑定当前项目和对话，迟到响应不回写新位置。指南、手机壳v68与静态资源白名单同步。\n\n## 验证\n\n- 首批42项检查通过；增加阅读入口的发布与费曼边界后，最终{n}项关联回归通过，失败／错误／跳过均为0，15个生产文件指纹前后相同。\n- 7项Node语法检查及{len(ui['checks'])}项实际电脑／配对HTTPS界面检查通过。模拟设计12次请求，返回此前范围及手机复用0次新请求。\n- 不新增原作业提交、评分、学习画像或掌握度。\n- 另1次真实Flash/high原生单题流程，{live['model_requests']}次模型请求，{live['seconds']}秒，{total_tokens}总Token；仅生成所选原第1题的卡点，没有生成另一处。不是全任务提速对照。\n\n## 人工内容核对与限制\n\n新题情境有变化并要求理由，设计解答与独立解答的主结论没有冲突。题干对理想点电荷定义域和位置不同的条件仍不够明确，自动核查漏检；点电荷场的性质也可能是额外前置。原始文件保留，不静默改写或将单样例当作全面质量认证。\n\n没有实体安卓、完整Word分页或整个软件性能认证；编程作业沿用原入口，本项用于普通习题。\n\n验收页：[{target.name}]({target.as_posix()})\n''',encoding='utf-8')
    class Links(HTMLParser):
        def handle_starttag(self,tag,attrs):
            for key,value in attrs:
                if key not in ('src','href') or not value:continue
                parts=urlsplit(value);assert not parts.scheme and not parts.netloc,value
                assert (OUT/unquote(parts.path)).resolve().is_file(),value
    Links().feed(page);print(str(target),flush=True)


if __name__=='__main__':main()
