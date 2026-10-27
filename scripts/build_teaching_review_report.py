"""Openable audit UI with retained real reviews, not new model benchmarks."""
from html import escape
import json
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/teaching-review-acceptance-20261021'
TITLE = '教学核查记录与阅读验收'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    specs = [
        ('review-duplicate-real-20261021-1', 'narrow', 'duplicate', '重复段落：已记录两处局部修订', '重复门槛_重复段落编号（已采用）.docx',
         '这份已保存的真实核查实际使用两个段落编号。面板保留建议与应用记录；原段全文未单独保存在编号提议中，因此不从后来正文猜补。定位成功不证明建议正确。'),
        ('review-passages-real-20261021-1', 'baseline', 'gauss', '高斯定律：有修订，也仍有核查局限', '高斯_旧快速核查.docx',
         '旧流程实际把“区域”改为“全空间”。这只是一次快速核查的局部结果，不能把它理解为整篇的所有引用、推论均已确认。'),
        ('review-passages-real-20261021-1', 'registered', 'gauss', '反例：返回通过仍然可能漏检', '高斯_普遍提供编号（未采用）.docx',
         '这是此前被拒绝的普遍编号候选，不是当前默认方案。本次返回passed=true、issues=[]，却漏掉旧流程发现的范围歧义。保留它是为了让“本轮未列出疑点”与“证明全篇正确”有明确区别。'),
        ('review-passages-real-20261021-1', 'baseline', 'rate', '反应速率：修正总结不等于正文全对', '速率_旧快速核查.docx',
         '实际核查修改了总结中过强的必要性表述，正文中的B表观零级等内容仍待进一步核对。历史意见与修订前后都保留，不用通过标记遮蔽这些限制。'),
    ]
    rows = []
    for folder, phase, ident, title, word, note in specs:
        record = next(row for row in json.loads((ROOT / 'build' / folder / (phase + '-results.json')).read_text(encoding='utf-8')) if row['case'] == ident)
        assert record['status'] == 'completed'
        assert (ROOT / 'build/review-duplicate-acceptance-20261021' / word).is_file()
        rows.append({'id': ident + '-' + phase, 'title': title, 'note': note, 'model': 'deepseek-flash / high',
                     'seconds': round(record['seconds'], 2), 'metadata': {'reviews': record['reports']},
                     'word': '../review-duplicate-acceptance-20261021/' + word})
    ui = json.loads((ROOT / 'build/teaching-review-ui-20261021-1/teaching-review-ui-report.json').read_text(encoding='utf-8'))
    assert ui['passed'] and ui['external_model_requests'] == 0
    tests = ET.parse(ROOT / 'build/teaching-review-final-regression-20261021.xml').getroot().findall('.//testcase')
    assert all(t.find(k) is None for t in tests for k in ('failure', 'error', 'skipped'))
    css = (ROOT / 'web/teaching_review.css').read_text(encoding='utf-8')
    script = (ROOT / 'web/teaching_review.js').read_text(encoding='utf-8')
    data = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
    items = ''.join('<li>' + escape(value) + '</li>' for value in ui['checks'])
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>:root{--surface:#fffefa;--ink:#234136;--line:#cbd7cf;font-family:system-ui,"Microsoft YaHei",sans-serif;background:#f1f3ec;color:var(--ink)}*{box-sizing:border-box}body{max-width:1100px;margin:0 auto;padding:28px 18px;line-height:1.8}h1{line-height:1.4;font-size:30px}h2{font-size:21px}a{color:#196b52}button,input{font:inherit;color:inherit;background:#f6f8f2;border:1px solid var(--line);border-radius:8px;padding:7px 12px}header,.panel{padding:24px;margin:18px 0;border:1px solid var(--line);border-radius:18px;background:var(--surface)}.notice{border-left:4px solid #b48438;padding:12px;background:#faf2dc}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.panel{margin:0;min-width:0}.meta{font-size:13px}.teaching-review-body{max-height:560px}code{overflow-wrap:anywhere}li{margin:7px 0}@media(max-width:760px){body{padding:12px}.grid{grid-template-columns:1fr}.panel,header{padding:16px}h1{font-size:25px}}__CSS__</style>
<header><div>STUDYFORGE · 2026-10-21</div><h1>看清哪里改过，哪里还需核对</h1><p>电脑和手机成果区新增“教学核查记录”。本页使用同一显示组件，载入4份此前保存的真实模型核查；没有重新请求模型，也不把它们算作本轮新的能力或速度试验。</p>
<p><a href="../../验收最新版.vbs">启动最新版源码</a> · <a href="../../web/help/guide.html#teaching-review">软件内操作指南</a> · <a href="../../docs/教学核查记录与阅读验收.md">本轮完整验收说明</a></p>
<div class="notice"><strong>核查卡片改善的是可追查性，不代表模型已经不会漏检。</strong>新卡片明确区分局部修订、历史疑点、未执行独立核查和未列出疑点；查看不新增模型请求、不出题、不写画像。原来的教学与审查设置保持，源码未打包。</div></header>
<div class="grid" id="samples"></div><section class="panel"><h2>本轮实际验证</h2><p>__COUNT__ 项Python相关回归、3项Node状态检查通过。另有7项真实Electron／配对HTTPS手机界面检查；界面夹具使用可控模型响应，原生快速与极速两个DOCX任务共3次受控请求、0次外部模型请求，不是新一轮真实模型讲解评测。</p><ul>__CHECKS__</ul><p>实测覆盖320／390像素宽度、深色主题、内部滚动与刷新、长文字展开、53条疑点的末页跳转、字面HTML处理和习题私有解析隔离。没有在实体安卓设备或Microsoft Word中做本轮人工排版验收，也没有测整个软件的内存／长视频耗时。</p>
<p><a href="../teaching-review-ui-20261021-1/电脑教学核查记录.png">电脑截图</a> · <a href="../teaching-review-ui-20261021-1/手机教学核查记录-390.png">手机截图</a> · <a href="../teaching-review-ui-20261021-1/teaching-review-ui-report.json">界面运行记录</a></p></section>
<script>__COMPONENT__</script><script type="application/json" id="data">__DATA__</script><script>const rows=JSON.parse(document.getElementById('data').textContent);for(const row of rows){const card=document.createElement('article');card.className='panel';const title=document.createElement('h2');title.textContent=row.title;const note=document.createElement('p');note.textContent=row.note;const meta=document.createElement('p');meta.className='meta';meta.textContent='此前真实核查 · '+row.model+' · 当时耗时 '+row.seconds+' 秒（非本轮重测）';const review=studyforgeTeachingReview.create(row.metadata,row.id,'explanation');const link=document.createElement('a');link.href=row.word;link.textContent='打开这次核查当时交付的 Word';card.append(title,note,meta,review,link);document.getElementById('samples').append(card);review.open=true;}window.reportReady=true;</script></html>'''
    for key, value in {'TITLE': TITLE, 'CSS': css, 'COUNT': str(len(tests)), 'CHECKS': items,
                       'COMPONENT': script, 'DATA': data}.items():
        page = page.replace('__' + key + '__', value)
    (OUT / (TITLE + '.html')).write_text(page, encoding='utf-8')
    (OUT / 'manifest.json').write_text(json.dumps({'samples': 4, 'program_checks': len(tests),
        'node_checks': 3, 'ui_checks': len(ui['checks']), 'new_external_model_requests': 0,
        'source': 'retained_actual_reviews_not_new_benchmark'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(OUT / (TITLE + '.html'))


if __name__ == '__main__': main()
