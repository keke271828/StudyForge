"""Preserve acceptance for dependent teaching and failed Codex turns."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import sqlite3
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/followup-versions-acceptance-20261025'
UI=ROOT/'build/followup-versions-ui-20261025-2'
GATE=ROOT/'build/followup-versions-final-20261025'
TITLE='后续教学版本核对与限流提示验收'


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    gate=load(GATE/'command.json');ui=load(UI/'ui-report.json');state=load(UI/'ui-state.json');followup=load(UI/'followup-state.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and len(gate['production_before'])==11
    assert not any(gate['tests'][key] for key in ('failure','error','skipped'))
    assert ui['passed'] and len(ui['checks'])==8 and not ui['console_errors'] and ui['controlled_model_calls']==8
    assert len(followup['turns'])==2 and all(t['verified_notice'] and t['unknown_notice'] for t in followup['turns'])
    assert len(state['submissions'])==4 and len(state['events'])==2
    db=sqlite3.connect('file:'+str(UI/'data/studyforge.sqlite3')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    samples=[]
    for item in ui['completed']:
        artifact=db.execute('SELECT path FROM artifacts WHERE id=?',(item['feedback_artifact_id'],)).fetchone()
        path=Path(artifact['path'])
        with ZipFile(path) as archive:
            assert archive.testzip() is None
            root=ET.fromstring(archive.read('word/document.xml'))
            body='\n'.join(''.join(p.itertext()) for p in root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
        assert '针对性讲解' in body and '90' in body and 'NEW_PARENT' not in body
        name='已核实版本_批改样例.docx' if item['version_verified'] else '旧基准未核实_批改样例.docx'
        samples.append({'name':name,'path':path,'body':body,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    db.close()
    if OUT.exists():raise SystemExit('Preserve the earlier acceptance report.')
    OUT.mkdir()
    for item in samples:shutil.copy2(item['path'],OUT/item['name'])
    report={'date':'2026-10-25','gate':gate,'ui':ui,'followup':followup,
        'samples':[{k:v for k,v in item.items() if k in ('name','sha256')} for item in samples],
        'packaged':False,'limits':['controlled responses, no real rate-limit recovery guarantee',
            'no physical Android, Word pagination or global performance certification']}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    total=gate['tests']['total']
    body=''.join('<details><summary>'+item['name']+'</summary><p><a href="'+item['name']+'">下载原生批改 Word</a></p><pre>'+html.escape(item['body'])+'</pre></details>' for item in samples)
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>后续教学版本核对与限流提示验收</title><style>
:root{color:#243e35;background:#eeeee8;font:16px/1.85 "Microsoft YaHei",sans-serif;color-scheme:light}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:28px 20px 65px}header,section{background:#fffef9;border:1px solid #d8dfd5;border-radius:20px;padding:25px 30px;margin-bottom:20px}h1{font-size:30px;line-height:1.4}h2{font-size:23px}a{color:#126c58;text-underline-offset:3px}.eyebrow{font-size:13px;letter-spacing:.1em;color:#52796a}.note{padding:16px 20px;background:#fff0da;border-left:4px solid #c28b34;border-radius:12px}li{margin:9px 0}img{display:block;max-width:100%;border:1px solid #d7dfd6;border-radius:14px;margin:16px auto}details{border:1px solid #dce2d8;border-radius:14px;padding:15px 18px;margin:16px 0}summary{font-weight:650;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f3ed;padding:18px;border-radius:12px;font:14px/1.9 "Microsoft YaHei",sans-serif}@media(max-width:650px){main{padding:14px 9px}header,section{padding:20px 16px}h1{font-size:25px}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-25</div><h1>让后续教学保留原评分依据</h1><p>补齐“版本记录已保存，后续再练却仍拿旧成绩配新题”的缺口；同时修复用户反馈的 Codex 429 原始字典和失败后残留等待提示。</p><p><a href="../../验收最新版.vbs">最新版源码启动入口</a> · <a href="../../web/help/guide.html#homework">软件内指南</a> · <a href="report.json">验收摘要</a></p><p>从 Windows 托盘彻底退出旧 StudyForge，再在资源管理器双击“验收最新版.vbs”；手机刷新。本次未重新打包。</p></header>
<section><h2>后续教学修复</h2><ul><li>错因再练在使用旧评分前核对题面、参考解析、标准和难度。已知版本不同就停止，保留旧成绩与批改，不退回只按分数生成新题。</li><li>新情境理解检查同样核对基准。主动指定已变更题单会提示核对；自动选择时跳过已知变更的题，仍可选择可用的其他已完成检查。</li><li>旧记录没有版本依据时保留使用入口，并明确“版本未核实”。该题面可作出题参考，不能据此认定已完成严格可比的迁移或能力提升。</li><li>画像卡片、导师摘要和结构化近期评估区分“同题版本已核实／未核实”。帮助条件、间隔和原分数分别保留，不把版本一致当作独立完成或稳定掌握。</li></ul><img src="../followup-versions-ui-20261025-2/desktop-profile-version-boundary.png" alt="两种近期复习记录分别注明已核实和未核实的同题版本"><p>以上检查在本机完成，没有增加固定的模型审查轮数。</p></section>
<section><h2>截图中的 Codex 429</h2><p>HTTP 429 表示服务拒绝了当前请求；截图明确包含“重试次数已到上限”。短时请求过密、并发与账号使用限制都需结合实际服务状态区分，单凭该信息不能断定总额度用完。已读取的当前 Codex 账号用量为 5 小时已用约 61%、周已用约 21%，且允许常规使用；没有据此认定 StudyForge 登录的必然是同一账号。</p><p>现在这类错误会显示中文说明与“本次回复已停止”，保留原始结构化诊断供程序处理；失败或停止后清除等待状态，问题仍可重新发送。不会用修改提示词来假装解除服务端限制。</p><p><a href="https://learn.chatgpt.com/docs/app-server">OpenAI 官方 App Server：账号与用量读取</a> · <a href="https://developers.openai.com/api/docs/guides/error-codes">OpenAI 官方错误码与限流处理</a></p><img src="../followup-versions-ui-20261025-2/desktop-codex-rate-limit.png" alt="受控 Codex 限流后清除等待状态，并给出中文恢复提示"><p class="note">界面验收使用受控 429，不代表真实服务已经解除限流。实际使用时应减少同时进行的 Codex 任务，稍后再试，持续出现时核对软件实际登录账号的用量。</p></section>
<section><h2>验证</h2><p>最终 __TOTAL__ 项关联回归全部通过，失败、错误、跳过均 0，11 个生产文件前后指纹一致。新增 16 项后续教学检查及 4 项 Codex 错误检查；5 项 JavaScript 语法检查通过。</p><p>8 组实际电脑／配对 HTTPS 手机界面检查通过：保存版本与旧基准作答、再练入口版本校验、画像提示、原生 Codex 429 结束状态与同对话重试。6 次评分／补讲调用与 2 次受控导师回合，总计 8 次受控调用，真实云调用 0。保留 2 份种子提交、2 份原生复习提交、2 条新增评分证据，没有因失败、查看或重试导师回复新增测验分数。</p><p>两份原生批改 DOCX 下载、压缩包和正文核对通过。指南与手机壳 v77 同步。本轮不认证真实模型教学质量、真实限流解除、实体安卓、Word 分页或整体速度／内存。</p><p><a href="../followup-versions-final-20261025/command.json">最终命令与指纹</a> · <a href="../followup-versions-final-20261025/regression.xml">回归 XML</a> · <a href="../followup-versions-ui-20261025-2/ui-report.json">两端记录</a> · <a href="../followup-versions-ui-20261025-2/followup-state.json">受控导师输入边界</a> · <a href="../followup-versions-red-20261025.xml">修复前 16 项针对性失败</a></p><details><summary>中途记录</summary><p>首次关联检查 93 项通过、1 项失败：原测试限制近期摘要只能有旧字段，现已明确增加无私有内容的版本布尔字段。首次 UI 已通过评分和画像检查，随后因脚本只修改下拉框而没有切换对话服务，被原有归属校验拦住。最终在正确创建的独立 Codex 对话中按实际发送流程验证，没有放宽生产校验。</p></details></section>
<section><h2>受控批改样例</h2><p>以下均为完整提交后原生生成的受控 90 分样例，用于检验记录和交付，不作模型能力评判。</p>__SAMPLES__</section></main></html>'''
    (OUT/(TITLE+'.html')).write_text(page.replace('__TOTAL__',str(total)).replace('__SAMPLES__',body),encoding='utf-8')
    document=f'''# 后续教学版本核对与限流提示验收

2026-10-25，源码更新，未打包。

- 错因再练及新情境检查核对旧评分对应的题面、参考解、标准和难度；已知变更不再降级为按旧成绩对新题出题。自动基准选择跳过变更记录，历史成绩保留。
- 缺少版本证据的旧记录仍可使用并明确未核实；画像近期评估、导师文本与结构化摘要保留同题版本是否已核实，不把间隔直接当成保持证明。
- Codex 结构化 429 显示中文限流及本次停止提示；保留原始诊断供程序处理，失败后清空等待状态，原问题可重发。软件不能解除服务端限制。
- 最终 {total} 项关联回归通过，失败／错误／跳过均 0，11 个生产文件指纹一致；新增16项后续教学及4项Codex检查，5项JavaScript检查通过。
- 8组实际电脑／配对HTTPS手机操作通过；受控8调用（6评分与补讲、2导师回合），云调用0。原生复习2份、种子2份、评分证据2条，未因导师失败重试增加分数。两份原生Word下载、压缩包及正文核对通过。
- 首次聚焦93通过1失败是摘要字段约定需增加版本布尔值；首次UI服务切换夹具不完整，被已有归属校验拒绝，改用真正独立Codex对话后完整验收。

验收页：[后续教学版本核对与限流提示验收.html](C:/Users/Lenovo/Documents/ChatGPT/codex workspace/build/followup-versions-acceptance-20261025/后续教学版本核对与限流提示验收.html)

先托盘退出旧StudyForge，再双击验收最新版.vbs；手机刷新。指南与手机壳v77同步。受控模型和手机尺寸窗口不认证真实教学、真实限流解除、实体安卓、Word分页或整体性能。未打包，未新增关机动作。
'''
    (ROOT/'docs/后续教学版本核对与限流提示验收.md').write_text(document,encoding='utf-8')
    path=ROOT/'docs/当前功能状态与待验收清单.md';text=path.read_text(encoding='utf-8')
    entry=f'2026-10-25 完成 [后续教学版本核对与限流提示](后续教学版本核对与限流提示验收.md)：错因再练和新情境基准核对原评分版本，已知变更不配旧成绩与新题；未知旧版保留入口并注明边界，画像／导师近期摘要区分同题版本核实状态。Codex结构化429改中文提示，失败清除等待且可原问题重试。最终{total}项关联回归、8组两端操作和5项语法检查通过，11个生产文件指纹一致；受控8调用、云调用0，原生复习2份、评分2条，Word下载／压缩包／正文通过。不认证真实模型、限流解除、实体安卓、分页或整体性能；指南与手机壳v77，未打包。\n\n'
    if '[后续教学版本核对与限流提示]' not in text:path.write_text(text.replace('## 已有实现及验收记录\n\n','## 已有实现及验收记录\n\n'+entry,1),encoding='utf-8')
    print(json.dumps({'report':str(OUT/(TITLE+'.html')),'tests':total,'ui_checks':len(ui['checks'])},ensure_ascii=False))


if __name__=='__main__':main()
