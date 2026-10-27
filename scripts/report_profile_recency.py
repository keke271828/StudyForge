"""Save local acceptance for recent assessments and dated historical doubts."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import sqlite3
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/profile-recency-acceptance-20261023'
UI=ROOT/'build/profile-recency-ui-20261023-4'
GATE=ROOT/'build/profile-recency-final-20261023-3'
TITLE='近期评估与历史疑问教学适配验收'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate=load(GATE/'command.json');ui=load(UI/'ui-report.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed']
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert len(ui['checks'])==5 and ui['controlled_model_calls']==5
    if OUT.exists():raise SystemExit('Preserve the existing acceptance report.')
    OUT.mkdir()
    db=sqlite3.connect('file:'+str(UI/'data/studyforge.sqlite3')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    artifact=dict(db.execute('SELECT * FROM artifacts WHERE id=?',(ui['feedback_artifact_id'],)).fetchone())
    submissions=[dict(row) for row in db.execute('SELECT id,score FROM submissions')]
    evidence=[{'recorded_at':row['created_at'],'kind':row['kind'],
        **{key:json.loads(row['payload_json']).get(key) for key in ('topic','score','practice_context')}}
        for row in db.execute("SELECT kind,created_at,payload_json FROM learning_events WHERE kind='做题' ORDER BY id")]
    assert len(submissions)==1 and submissions[0]['score']==90 and [item['score'] for item in evidence]==[40,90]
    db.close()
    target=OUT/'手机提交后的原生批改示例.docx';shutil.copy2(artifact['path'],target)
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        document=ET.fromstring(archive.read('word/document.xml'))
        text='\n'.join(''.join(p.itertext()) for p in document.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
    assert '90' in text and '学生自报参考过笔记' in text and '针对性讲解' in text
    (OUT/'原生批改正文.txt').write_text(text,encoding='utf-8')
    report={'date':'2026-10-23','gate':gate,'ui':ui,'evidence':evidence,'submissions':submissions,
        'artifact':{'filename':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'package_verified':True},
        'packaged':False,'limits':['mock scores and replies','no physical Android check','no Word pagination check','no overall performance claim']}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    total=gate['tests']['total']
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>近期评估与历史疑问教学适配验收</title><style>
:root{color-scheme:light;color:#243e35;background:#efeee8;font:16px/1.85 "Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:30px 20px 65px}header,section{background:#fffdf8;border:1px solid #d8dfd5;border-radius:20px;padding:26px 30px;margin-bottom:20px}h1{font-size:30px;line-height:1.4}h2{font-size:23px}.eyebrow{font-size:13px;letter-spacing:.12em;color:#4d7868}.good,.note{border-radius:12px;padding:16px 20px}.good{background:#e8f3eb}.note{background:#fff0d8;border-left:4px solid #bc8a35}a{color:#116c58;text-underline-offset:3px}li{margin:8px 0}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #dce1d7;text-align:left;vertical-align:top}img{max-width:100%;display:block;border:1px solid #dce1d7;border-radius:14px;margin:15px auto}.phone{max-width:320px}details{border:1px solid #dce1d7;border-radius:14px;padding:14px 18px;margin:15px 0}summary{font-weight:650;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f3ed;padding:18px;border-radius:12px;font:14px/1.9 "Microsoft YaHei",sans-serif}@media(max-width:650px){main{padding:14px 9px}header,section{padding:20px 16px}h1{font-size:25px}table{font-size:14px}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-23 · SOURCE ACCEPTANCE</div><h1>把近期作答与历史疑问分开看</h1><p>画像原来主要给出历史加权分；现在同时列出近期评估，让导师结合后续证据核对旧疑问。</p><p><a href="../../验收最新版.vbs">最新版源码启动入口</a> · <a href="../../web/help/guide.html#profile">软件内指南</a> · <a href="report.json">验收摘要与文档指纹</a></p><p>从Windows托盘彻底退出旧StudyForge，再在资源管理器双击“验收最新版.vbs”。手机连接后刷新。本次更新源码，未打包EXE。</p></header>
<section><h2>最直观的区别</h2><table><tr><th>同一知识点的记录</th><th>过去主要显示</th><th>现在额外提供</th></tr><tr><td>以前40分，后来90分</td><td>历史加权参考分55</td><td>最近90分、此前40分分别列出，不把55当成最近一次成绩。</td></tr><tr><td>这次参考过笔记，旧条件未知</td><td>总体支持次数</td><td>每条近期记录保留各自帮助边界；未记录不等于没有帮助。</td></tr><tr><td>曾经问过某概念，此后已有作答</td><td>旧疑问仍是暂定判断</td><td>提醒“历史疑问，此后已有评估，当前状态待核对”；不长期据旧疑问断定仍不会，也不因一次高分自动认定已解决。</td></tr></table><div class="good">历史参考分、试卷原分数、80分通过线及自评权重保持原规则。新功能在本机整理，不增加一轮模型判断或固定审查。</div><p>最近最多3条有分数的做题、费曼或编程评估，按证据记录时间排序。自评、未确认最终分数的静态反馈和已移出的评估不混入。题目、难度和帮助条件可能不同，分差不直接代表能力变化。</p></section>
<section><h2>学习记忆怎样跟上变化</h2><ul><li>聊天导师、讲解生成的画像输入和跨项目画像工具都能看到近期评估；原对话记录与学生答案仍隔离。</li><li>旧疑问的先后采用原学习证据时间，较晚的后台整理、移出后恢复不会把它伪装成新疑问。你主动纠正的判断继续优先，并标为未验证。</li><li>新提出的疑问保留为当前问题，不因为之前曾有高分而忽略。</li><li>已启动的文档仍使用原画像快照；正常新作答不悄悄改写正在进行的任务。用户纠正／移出等原有控制继续按现有规则刷新。</li></ul><p>日期在电脑卡片中按本机时区显示；模型摘要中的评估时间明确注明UTC，用于区分记录先后。它仍是有限摘要，不自动推断知识点的所有方面都已掌握。</p></section>
<section><h2>实际两端操作</h2><ol><li>电脑初始只显示旧40分及“帮助条件未完整记录”，查看没有模型请求。</li><li>手机原生提交一题，自报参考过笔记；两次受控评分与一次错因补讲完成，生成原生Word。电脑显示最近90、此前40，历史参考55。</li><li>电脑通过画像原生控制移出、恢复这条新评估，近期列表随之重算；作业成绩仍90，没有新增作答或模型请求。</li><li>手机导师请求收到近期记录、帮助说明和旧疑问提示；没有带入原聊天或旧学生答案。</li><li>另一项目的独立对话同样收到画像摘要，聊天保持隔离；手机能下载已交付的批改Word。</li></ol><img src="../profile-recency-ui-20261023-4/desktop-recent-records.png" alt="电脑同时显示历史参考55分与最近90、此前40分，以及各自帮助条件"><details><summary>展开320px深色手机截图</summary><img class="phone" src="../profile-recency-ui-20261023-4/phone-profile-summary.png" alt="手机导师显示近期表现与历史疑问的核对提示"></details></section>
<section><h2>验证结果</h2><p>最终__TOTAL__项关联回归全部通过，失败、错误、跳过均0；6个生产文件测试前后指纹一致。21项新针对性检查包括新旧证据、时区排序、保留上限、移出恢复、自评与静态反馈排除、原疑问时间、用户纠正、独立项目导师与文档输入及原任务快照。中途56项聚焦检查与最终范围重叠，不累加。</p><p>5项实际电脑／配对HTTPS手机检查通过，控制台错误0。5次受控调用：2次评分、1次补讲、2次导师回复，真实云调用0。测验提交1份，真实保存的测验分数90；做题画像证据2条（旧40分是种子记录，新90分来自原生提交）。近期列表查看和画像移出恢复没有模型请求。相关JavaScript语法检查、报告链接检查及Word压缩包／正文检查通过，指南和手机壳v74同步。</p><p><a href="../profile-recency-final-20261023-3/command.json">最终命令与指纹</a> · <a href="../profile-recency-final-20261023-3/regression.xml">回归XML</a> · <a href="../profile-recency-ui-20261023-4/ui-report.json">实际两端记录</a> · <a href="../profile-recency-red-20261023.xml">新增目标行为的原始检查</a></p><details><summary>过程中的问题也保留</summary><ul><li>新增目标行为最初16项未满足，主要为尚无近期记录与历史疑问标记，不等于16个独立故障。</li><li>首次聚焦49项通过、2项失败，验收预期错误地禁止了原有合法评分摘要；改为只限制新增近期字段不携带作答、评分正文或私有标识。原话与原聊天仍排除。</li><li>第一轮完整回归289项通过、1项失败，是验收桩把流式响应送给普通请求；改为软件实际使用的Agent文档通道后针对性检查通过。</li><li>第二轮290项程序检查通过，但测试期间继续修正原证据时间，源码指纹不一致，门禁未通过；本页采用最后一次固定源码完整重跑。</li><li>首次UI夹具创建另一对话后改变了默认项目；显式恢复目标项目后流程通过。一次自动权限审查超时未启动进程，获准重试后完成，不当作产品故障。</li></ul></details><p class="note">本轮证明记录与教学输入正确接续，不证明真实模型因此讲得更好。分数与回复由验收桩提供，未重测实体安卓、Word分页或全软件内存／长任务速度；没有更换生产模型、教师提示词或增加审查轮数。</p></section>
<section><h2>原生批改样例</h2><p><a href="手机提交后的原生批改示例.docx">下载手机提交后生成的批改Word</a> · <a href="原生批改正文.txt">查看正文文本</a></p><details><summary>展开已完整提交的合成作答与批改正文</summary><pre>__BODY__</pre></details></section></main></html>'''
    (OUT/(TITLE+'.html')).write_text(page.replace('__TOTAL__',str(total)).replace('__BODY__',html.escape(text)),encoding='utf-8')
    document=f'''# 近期评估与历史疑问教学适配验收

2026-10-23，源码更新，未打包。

## 修改

- 每个知识点增加最多3条近期有分数评估，时间排序后列出做题／费曼／编程类型、分数、原帮助条件和已有复习间隔。自评、未确认分数的静态反馈、移出评估不混入；原加权分、作业成绩及80分通过线不改。
- 电脑知识点卡片分列近期记录与历史参考；日期按本机时区显示。模型摘要的评估时间标UTC，导师、讲解生成及跨项目画像工具均收到有限近期摘要，不增加原话、作答或私有标识。
- 旧疑问之后已有评估时标为历史疑问，提醒结合近期作答核对现状；不自动删除疑问或宣布掌握。先后以原学习证据时间为准，后台晚整理或恢复旧判断不改变证据时间；新疑问和用户纠正继续有效。
- 查看、移出／恢复画像不调用模型、不重复作答，已启动文档继续沿用原画像快照。指南和手机壳v74同步，未改生产教师提示词或新增固定核查。

## 验证

- 最终{total}项关联回归全通过，失败／错误／跳过均0；6个生产文件指纹一致。新针对性21项；中途56项聚焦检查与最终范围重叠，不累加。
- 5项实际电脑／配对HTTPS手机操作通过：手机原生提交、画像90与40及参考55分列、帮助自报、画像移出恢复不改测验分、另一项目与手机导师输入、原生Word下载。控制台错误0。
- 原生提交1份，成绩90；做题画像证据2条，旧40分是合成种子记录，新90分来自实际提交流程。受控模型5次（评分2、分析1、导师2），真实云调用0；查看和画像控制不增加模型请求。
- 新增目标行为最初16项未满足。首次聚焦2项验收预期过宽已更正；首次完整回归289通过／1个桩协议失败，针对性复核通过。第二轮290项程序检查通过，但测试期间继续修正原证据时间，指纹门禁未通过；最终重新固定源码完整重跑，不把中间结果冒作最终验收。首次UI项目初始化和一次权限审查超时单列保留。
- 相关JavaScript语法与报告链接检查通过。原生DOCX核对压缩包、正文与指纹，截图已检查。

## 打开与边界

从Windows托盘彻底退出旧StudyForge，在资源管理器双击“验收最新版.vbs”；手机连接后刷新。

验收页：[近期评估与历史疑问教学适配验收.html](C:/Users/Lenovo/Documents/ChatGPT/codex workspace/build/profile-recency-acceptance-20261023/近期评估与历史疑问教学适配验收.html)

本轮是记录、教师输入与交付流程检验，不是实际模型教学质量比较。未重新验收实体安卓、Word分页或全软件性能。源码未打包，没有新增自动出题或关机动作。
'''
    (ROOT/'docs'/('近期评估与历史疑问教学适配验收.md')).write_text(document,encoding='utf-8')
    status=ROOT/'docs/当前功能状态与待验收清单.md';current=status.read_text(encoding='utf-8')
    entry=f'2026-10-23 完成 [近期评估与历史疑问教学适配](近期评估与历史疑问教学适配验收.md)：知识点最多3条近期有分数评估与历史加权分分列，帮助／复习条件保留，自评及未定分静态反馈不混入。导师、讲解及画像工具收到近期摘要；旧疑问按原证据时间提示核对现状，晚整理或恢复不冒作新疑问，用户纠正优先。最终{total}项关联回归、5项实际电脑／配对HTTPS操作通过，6个生产文件指纹一致；原生提交1份90分、做题证据2条（旧40为种子），受控调用5次、云调用0。Word下载／压缩包／正文通过；不认证真实模型教学质量、实体安卓、Word分页或整体性能。指南与手机壳v74同步，源码未打包。\n\n'
    if '[近期评估与历史疑问教学适配]' not in current:status.write_text(current.replace('## 已有实现及验收记录\n\n','## 已有实现及验收记录\n\n'+entry,1),encoding='utf-8')
    print(json.dumps({'report':str(OUT/(TITLE+'.html')),'tests':total,'native_docx':target.name},ensure_ascii=False))


if __name__=='__main__':main()
