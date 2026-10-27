"""Inspectable native UI evidence; controlled replies are labelled as such."""
from html import escape
import json
from pathlib import Path
import shutil
import sqlite3
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'build/content-rounds-ui-20261021-3'
OUT = ROOT / 'build/content-rounds-acceptance-20261021'
TITLE = '讲解新疑问与连续核对验收'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = json.loads((FIXTURE / 'content-rounds-ui-report.json').read_text(encoding='utf-8'))
    assert result['passed'] and result['external_model_requests'] == 0
    cases = ET.parse(ROOT / 'build/content-rounds-final-regression-20261021.xml').getroot().findall('.//testcase')
    assert all(t.find(k) is None for t in cases for k in ('failure', 'error', 'skipped'))
    case = json.loads((FIXTURE / 'case.json').read_text(encoding='utf-8'))
    with sqlite3.connect((FIXTURE / 'data/studyforge.sqlite3').as_uri() + '?mode=ro', uri=True) as database:
        database.row_factory = sqlite3.Row
        original = dict(database.execute('SELECT * FROM lesson_questionnaires WHERE id=?', (case['root_feedback_id'],)).fetchone())
        rounds = [dict(row) for row in database.execute('SELECT * FROM lesson_content_checks ORDER BY created_at,rowid')]
        artifact = dict(database.execute('SELECT * FROM artifacts WHERE id=?', (case['artifact_id'],)).fetchone())
        assert len(rounds) == 2 and all(row['reply_status'] == 'completed' for row in rounds)
        cards = []
        for index, row in enumerate(rounds):
            reply = database.execute('SELECT content FROM messages WHERE id=?', (row['reply_message_id'],)).fetchone()['content']
            focus = json.loads(row['focus_json'])
            cards.append('<article class="panel"><span class="badge">' + ('电脑端' if index == 0 else '配对手机端') +
                ' · 核对完成</span><h2>第 ' + str(index + 1) + ' 次新疑问</h2><h3>实际提交的问题</h3><blockquote>' +
                escape(row['other_text']) + '</blockquote><p>定位：' + escape(' → '.join(focus.get('path', [])) or '按填写的问题定位') +
                '</p><details><summary>查看夹具实际保存的导师回复（受控响应）</summary><pre>' + escape(reply) + '</pre></details>' +
                '<p class="muted">这条记录有独立的提问和回复ID，保留原讲解任务及原对话关系。不是重新提交原问卷，也未生成练习。</p></article>')
        assert original['status'] == 'skipped'
    word = '统一门槛_原生快速核查讲解.docx'
    shutil.copy2(artifact['path'], OUT / word)
    assert zipfile.is_zipfile(OUT / word)
    with zipfile.ZipFile(OUT / word) as package:
        assert package.testzip() is None
        ET.fromstring(package.read('word/document.xml'))
    checks = ''.join('<li>' + escape(item) + '</li>' for item in result['checks'])
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#234438;background:#f0f3ed}*{box-sizing:border-box}body{max-width:1120px;margin:auto;padding:28px 18px;line-height:1.85}header,.panel{background:#fffefa;border:1px solid #ccd8ce;border-radius:18px;padding:24px;margin:18px 0;min-width:0}h1{font-size:30px;line-height:1.4}h2{font-size:22px}h3{font-size:16px}a{color:#176a4d}.notice{padding:14px;border-left:4px solid #b68d41;background:#fbf4e2}.badge{padding:5px 10px;border-radius:20px;background:#e4f0e6;font-size:13px}.muted{font-size:13px;color:#536a5b}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.grid .panel{margin:0}blockquote{margin:14px 0;padding:12px 16px;border-left:3px solid #508467;background:#eef5ed;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;padding:12px;background:#eef3eb;border-radius:8px}summary{cursor:pointer;font-weight:650}img{max-width:100%;height:auto;border:1px solid #ccd8ce;border-radius:12px}li{margin:7px 0}.steps{display:flex;flex-wrap:wrap;gap:10px}.steps span{padding:10px 14px;background:#e8f1e7;border-radius:10px}details{margin:14px 0}@media(max-width:760px){body{padding:12px}.grid{grid-template-columns:1fr}header,.panel{padding:16px}h1{font-size:25px}}</style>
<header><div>STUDYFORGE · 2026-10-21</div><h1>发现新疑问，可以接着核对</h1><p>已经提交或跳过理解问卷后，仍可针对同一讲解另开内容核对，保留此前的问题与回复。电脑和手机均可选择原章节／原句，填写后再保存或请导师回应。</p><p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../web/help/guide.html#teaching-review">软件内操作指南</a> · <a href="../../docs/讲解新疑问与连续核对验收.md">详细验收</a></p><div class="notice"><strong>本页来自真实应用操作，但模型回复使用受控夹具。</strong>它证明提交、恢复、保存、连续核对和范围保护等流程，不是本轮真实模型讲解能力评测。最终夹具为两个完整核对流程，共4次受控请求、0次外部请求；没有改动用户真实项目。源码未打包。</div></header>
<section class="panel"><h2>在软件中这样用</h2><div class="steps"><span>① 成果的“理解反馈”</span><span>② 核对讲解新疑问</span><span>③ 选章节／原句，填写问题</span><span>④ 仅保存，或提交请导师回应</span></div><p>旧反馈不覆盖；这份讲解已有未提交核对时复用该草稿。创建和仅保存不用模型，只有明确提交回应才开始核对。空问题又未选位置时先提示补充。核对后还可再开下一次。</p><p>恢复原项目、原对话、原资料及原任务保存的书库选择，不采用后来新选的节点；原版本检查失败时保留问题并提示，不悄悄改范围。新入口只核对讲解，不把内容质疑写成学习弱项、不扣分、不自动出题。原理解问卷中的自报困难和主动练习功能仍保留。</p><p><strong>原理解问卷状态：已跳过，完整保留。</strong>下面是随后在电脑和手机上独立完成的两次核对。</p></section>
<div class="grid">__CARDS__</div><section class="panel"><h2>实际检查</h2><p>__COUNT__ 项Python相关回归通过；3项共享核查组件Node检查及4份前端脚本语法检查通过。新流程有6项实际Electron／配对HTTPS手机操作检查。</p><ul>__CHECKS__</ul><p>新场景还检查了：同时打开复用草稿、已完成记录不可覆盖、原句逐字校验、原书库选择恢复、旧格式另存后继续、跨项目／对话拒绝、项目回收站拦截、失败重试不重复写提问、重启恢复、旧数据库增量建表和彻底删除后的外键完整性。初次测试发现手机接口白名单漏放行，已修正并用最终源码重跑通过。</p><p>这是配对HTTPS与320／390像素窗口检查，未在实体安卓设备人工验收；DOCX确认文件包可打开读取，不等于Microsoft Word分页视觉验收，也未重新测长视频速度、全应用内存或全学科教学质量。</p><p><a href="__WORD__">原生任务生成的讲解Word（受控文本）</a> · <a href="../content-rounds-ui-20261021-3/content-rounds-ui-report.json">完整界面运行记录</a></p></section>
<section class="panel"><h2>电脑端实际截图</h2><a href="../content-rounds-ui-20261021-3/电脑继续核对讲解.png"><img src="../content-rounds-ui-20261021-3/电脑继续核对讲解.png" alt="已完成的核对保留原问题，提供核对讲解新疑问入口" loading="lazy"></a></section><section class="panel"><h2>配对手机实际截图</h2><a href="../content-rounds-ui-20261021-3/手机继续核对-390.png"><img style="width:390px;max-width:100%" src="../content-rounds-ui-20261021-3/手机继续核对-390.png" alt="手机可恢复已完成的内容核对" loading="lazy"></a></section></html>'''
    for key, value in {'TITLE':TITLE, 'CARDS':''.join(cards), 'COUNT':str(len(cases)), 'CHECKS':checks, 'WORD':word}.items():
        page = page.replace('__' + key + '__', value)
    (OUT / (TITLE + '.html')).write_text(page, encoding='utf-8')
    (OUT / 'manifest.json').write_text(json.dumps({'program_checks':len(cases), 'ui_checks':len(result['checks']),
        'node_checks':3,'completed_content_rounds':2,'controlled_model_requests':4,'external_model_requests':0,
        'original_feedback_preserved':True,'learning_events':0,'mastery_updates':0,'automatic_exercises':0},ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUT / (TITLE + '.html'))


if __name__ == '__main__': main()
