"""Publish the recovery acceptance page only after real outputs and all receipts pass."""
import hashlib
import html
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
import zipfile
from docx import Document

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/manual-retry-final-20261026'
UI=ROOT/'build/manual-retry-ui-20261026-2'
OUT=ROOT/'build/manual-retry-acceptance-20261026'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def link(path,label):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(label)+'</a>'
def image(name,label):return '<figure><img loading="lazy" src="'+html.escape((UI/name).as_uri(),quote=True)+'" alt="'+html.escape(label,quote=True)+'"><figcaption>'+html.escape(label)+'</figcaption></figure>'


def main():
    gate,js,ui,flow=read(GATE/'command.json'),read(GATE/'javascript.json'),read(UI/'ui-report.json'),read(UI/'flow.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and js['exit_code']==0 and js['production_unchanged'] and ui['passed']
    assert not any(gate['tests'][key] for key in ['failure','error','skipped'])
    assert gate['production_after']=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in gate['production_after']}
    primary=ET.parse(GATE/'regression.xml').getroot().findall('.//testcase')
    focused=ET.parse(ROOT/'build/manual-retry-workers-20261026.xml').getroot().findall('.//testcase')
    assert all(not any(test.find(key) is not None for key in ['failure','error','skipped']) for test in focused)
    names=lambda rows:{(row.get('classname'),row.get('name')) for row in rows}
    unique=len(names(primary)|names(focused));assert len(primary)==228 and len(focused)==26 and unique==230
    log=(GATE/'javascript.log').read_text(encoding='utf-8');assert re.search(r'# fail 0\b',log)
    node_tests=int(re.search(r'# tests (\d+)',log)[1])
    assert len(ui['checks'])==4 and ui['controlled_model_requests']==10 and ui['external_model_requests']==0 and not ui['console_errors']
    assert len(flow['jobs'])==len(flow['receipts'])==2 and flow['failures']==2 and flow['calls']==10
    assert flow['mastery']==flow['learning_events']==0
    downloads=[]
    for job,name in zip(flow['jobs'],['desktop-recovered.docx','phone-recovered.docx']):
        assert job['status']=='completed';artifact=job['artifact'];path=UI/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==artifact['sha256']
        assert len([r for r in flow['receipts'] if r['job_id']==job['id']])==1
        for role in ['draft','review']:
            assert len([e for e in flow['events'] if e['job_id']==job['id'] and e['part']==1 and e['role']==role and e['phase']=='start'])==1
        with zipfile.ZipFile(path) as archive:assert archive.testzip() is None and b'<m:oMath' in archive.read('word/document.xml')
        words='\n'.join(p.text for p in Document(path).paragraphs)
        assert 'DRAFT_PART_1' in words and 'DRAFT_PART_2' in words and '系统性总结' in words
        downloads.append(link(path,'电脑恢复的Word样例' if name.startswith('desktop') else '手机恢复并下载的Word样例'))
    assert flow['jobs'][0]['project_id']!=flow['jobs'][1]['project_id']
    evidence=' · '.join([link(GATE/'command.json','相关回归和源文件指纹'),link(ROOT/'build/manual-retry-workers-20261026.xml','恢复专项测试'),link(GATE/'javascript.log','JavaScript模块测试'),link(UI/'ui-report.json','实际界面记录'),link(UI/'flow.json','实际任务与请求记录')])
    pictures=image('desktop-failed-retry.png','电脑：失败任务出现“重试未完成步骤”，并说明沿用原资料、模型与要求')+image('desktop-recovered.png','电脑：仍是同一个任务，恢复后得到完整讲解文件')+image('phone-failed-retry.png','手机：在“电脑后台任务”中直接恢复原任务')+image('phone-task-320.png','手机任务列表，320像素宽度，没有横向溢出')
    text=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>失败任务接续与Word交付验收</title><style>
body{{margin:0;background:#edf3ef;color:#234535;font:17px/1.85 "Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1150px;margin:auto;padding:30px 20px}}header,section{{background:white;border:1px solid #bdd1c1;border-radius:18px;padding:28px;margin-bottom:23px}}h1{{font-size:30px;line-height:1.45}}h2{{font-size:23px}}a{{color:#176747}}.stats{{display:flex;flex-wrap:wrap;gap:13px}}.stats b{{background:#e9f4e9;padding:9px 13px;border-radius:10px}}.note{{padding:14px 17px;background:#f1f4e9;border-radius:12px}}li{{margin:9px 0}}img{{max-width:100%;height:auto;border:1px solid #bdd1c1;border-radius:12px}}figure{{margin:24px 0}}figcaption{{font-size:14px;color:#516b5c}}figure:nth-last-child(-n+2) img{{max-width:390px}}@media(max-width:650px){{main{{padding:12px}}header,section{{padding:18px}}h1{{font-size:26px}}}}</style><main>
<header><small>StudyForge · 2026-10-26 · 本轮学习流程改进</small><h1>任务失败后，接着原进度完成</h1><p>讲解、习题文档、通读、知识整理和另存格式遇到可恢复的临时失败时，提供“重试未完成步骤”。保留原任务编号和完成步骤，并核对原资料版本。</p><div class="stats"><b>{unique}项去重后的相关测试通过</b><b>{node_tests}项JavaScript测试通过</b><b>4组实际界面验收</b><b>2份完整Word交付</b></div><p>{link(ROOT/'验收最新版.vbs','最新版启动文件：验收最新版.vbs')}</p><p class="note">先从Windows右下角托盘退出旧版，再双击启动文件。软件内F1指南补充了失败后接续的方法。本轮没有重新制作安装包。</p></header>
<section><h2>怎么用</h2><ol><li>在“成果文档”找到失败任务；手机打开“电脑后台任务”。</li><li>有“重试未完成步骤”时，点击后会核对原资料，再继续同一项任务。自动重试仍遵守该任务原来的设置。</li><li>任务沿用开始时的资料、模型和要求。失败后再聊天、清空资料选择，不会改写这项任务；想换模型或改要求，请重新生成一份。</li><li>没有恢复按钮时，阅读任务卡上的原因。内容检查未通过、原文件改动、记录删除或未完成步骤可能已经修改文件等情况，需要先处理。</li><li>作业批改继续从作业历史使用“重试批改”，保留原提交与成绩，不从通用恢复入口重新评分。</li></ol><p>同时修复了书库资料的暂停续做：以书库章节为主要资料时，会一并核对选定的原书范围，避免只核对项目文件造成误判。</p></section>
<section><h2>怎样验证“接着做”确实生效</h2><p>两份讲解都在第二章开始前受控中断：第一章写作与检查已经保存。电脑恢复一份，配对手机恢复另一项目的一份。每份的第一章写作和检查请求各只执行1次，后续补齐第二章与总结，再交付Word。两份共10次受控模型请求，没有请求外部模型。</p><ul><li>任务编号不变，没有新建重复任务；每个任务只产生一条手动恢复记录。</li><li>电脑清空当前资料选择、原对话出现后来要求后，旧任务的完整执行要求仍保持原样。</li><li>同一个恢复请求重复送达，不会再启动已完成任务。</li><li>手机下载文件与电脑保存文件的哈希一致，两个项目的成果分别展示。</li><li>原文件变化、取消、删除、内容检查失败、尚未确认的文件修改步骤，会阻止直接恢复。</li><li>实际通读、知识结构和纯排版工作流也经过恢复专项测试；原有评分与画像边界保持。</li></ul><p>相关回归228项，恢复专项26项，其中24项重复，去重后为230项；全部通过。JavaScript模块测试116项通过，{js['syntax_files']}份自有脚本通过语法检查。{evidence}</p></section>
<section><h2>可下载的受控验收文件</h2><p>{' · '.join(downloads)}</p><p class="note">这些是验证中断、章节复用、公式和下载链路的合成样例，不用于评价真实模型的教学质量。已检查Word文件结构、正文两章、总结与公式；尚未在Microsoft Word或安卓实机逐项检查排版。</p></section><section><h2>实际页面</h2>{pictures}</section></main></html>'''
    OUT.mkdir(exist_ok=True);report=OUT/'失败任务接续与Word交付验收.html';report.write_text(text,encoding='utf-8')
    record={'passed':True,'report':str(report),'unique_python_tests':unique,'related_tests':228,'focused_tests':26,'overlap':24,'node_tests':node_tests,'native_groups':4,'word_outputs':2,'external_model_requests':0,'source_only':True}
    (OUT/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'docs/失败任务接续与Word交付-20261026.md').write_text('# 失败任务接续与Word交付\n\n'
        '给可恢复的临时失败增加显式入口。项目任务保留原ID、资料、模型、要求和已完成步骤；先核对原资料版本。请求编号保证重复送达不重复执行。\n\n'
        '支持讲解/习题文档生成、通读、知识整理和另存格式；批改使用原作业恢复入口。内容、版本和未完成文件修改问题不直接重放。恢复记录仅保存必要的哈希和计数，不复制聊天正文。\n\n'
        '恢复可用性用小字段批量查询，不为任务列表加载完整资料或聊天。按任务加锁核对，结束后释放锁。\n\n'
        '230项去重后Python检查、116项JavaScript检查通过；实际电脑与HTTPS配对手机恢复两项任务并下载完整Word。\n\n'
        '报告：`build/manual-retry-acceptance-20261026/失败任务接续与Word交付验收.html`。\n\n'
        '复核：`scripts/verify_manual_retry.py`、`scripts/run_manual_retry.py`；历史证据目录不覆盖，重跑需新目录。\n\n'
        '双击 `验收最新版.vbs` 打开项目最新版，先从托盘退出旧软件。本轮未打包。\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':main()
