"""Present untouched real review outputs with separate inspection notes."""
import base64
import hashlib
import json
import re

from scripts.build_teaching_comparison import ROOT, TEMPLATE, inline_script


def build():
    before = ROOT / 'build/fast-review-20261014-before'
    after = ROOT / 'build/fast-review-20261014-after'
    target_folder = ROOT / 'build/fast-review-20261014'
    target_folder.mkdir(parents=True, exist_ok=True)
    inputs = json.loads((after / 'inputs.json').read_text(encoding='utf-8'))
    groups, audit_calls, inspections = [], 0, []
    for case in inputs:
        name = case['name']
        flawed = name == 'field-flawed'
        original_note = ('原回答有两处实质错误：把净电荷零写成没有场源；把强对称性写成必要条件。'
            '后文说对不能消除前面的错误。账目比喻“每一笔都不是零”也不精确：例子中四个侧面通量为零。'
            if flawed else '按本题要求人工检查未发现实质错误；不是全篇无误认证。作为避免审查过度改写的控制样例。')
        original_path = after / (name + '-original.md')
        original_text = original_path.read_bytes().decode('utf-8')
        rows = [{'case': name, 'arm': name + '-original', 'label': '实际原回答 · 原样保留',
            'text': original_text, 'sha256': hashlib.sha256(original_text.encode('utf-8')).hexdigest(), 'output': str(original_path),
            'metrics': '复用上一轮实际回答 · 本行没有重新调用模型', 'review': original_note,
            'request': {'original_file': case['original_file'], 'draft_sha256': case['draft_sha256']}}]
        for folder, label in ((before, '修复前的实际快速核查'), (after, '修复后的实际快速核查')):
            record = next(row for row in json.loads((folder / 'results.json').read_text(encoding='utf-8')) if row['case'] == name)
            if record['status'] != 'completed': raise ValueError('Keep failures separately; this report expects completed cases.')
            path = folder / record['answer_file']
            # Preserve the saved file bytes, including the Windows newlines of
            # the first probe. Its response hash was computed before file I/O.
            text = path.read_bytes().decode('utf-8')
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
            if hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest() != record['answer_sha256']:
                raise ValueError('Stored answer content does not match the response fingerprint.')
            request = json.loads((folder / (name + '-requests.json')).read_text(encoding='utf-8'))
            audit_calls += record['model_requests']
            note = ('本次两处原错误均被识别并应用精确替换，未重写整篇。修复前也做到了这一点；'
                '这不是本轮修复提高了模型识错能力的证据。账目比喻的余留措辞没有在本次核查中列出，仍需读者核对。'
                if flawed else '本次通过，最终正文与原回答逐字相同；没有为审查而添加章节或改写正确证明。')
            if flawed and folder == after:
                note += '新替换区分了球面对称推得该面径向场为零与整个内部场为零，不能由一个面的结果推广到内部。'
            rows.append({'case': name, 'arm': folder.name + ':' + name, 'label': label,
                'text': text, 'sha256': digest, 'output': str(path), 'metrics':
                f"{record['seconds']}秒 · 实际模型请求{record['model_requests']}次 · deepseek-flash / high · API直连",
                'review': note, 'request': {'calls': request, 'audit_reports': record['audit_reports']}})
            inspections.append({'case': name, 'round': folder.name, 'note': note,
                'audit_report_passed': record['audit_reports'][0]['passed'], 'answer_sha256': digest})
        title = {'field-flawed': '已知有错的物理讲解：发现问题后怎样修订',
                 'field-control': '物理控制样例：正确的主要内容应保留',
                 'proof-control': '数学控制样例：构造动机和证明应保留'}[name]
        groups.append({'case': name, 'round': '实际模型小样本核验', 'title': title,
            'question': case['requirements'], 'source': case['source'], 'rows': rows})
    payload = {'groups': groups, 'count': sum(len(group['rows']) for group in groups), 'failures': []}
    assets = ROOT / 'web/vendor'
    css = (assets / 'katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,'+
        base64.b64encode((assets / 'fonts' / m[1]).read_bytes()).decode()+')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    libraries = '\n'.join(inline_script((assets / file).read_text(encoding='utf-8'))
        for file in ('marked.js', 'purify.js', 'katex.js'))
    html = TEMPLATE.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c'))
    html = html.replace('__LIBRARIES__', libraries).replace('__RENDERER__', inline_script((ROOT / 'web/lesson_render.js').read_text(encoding='utf-8')))
    html = html.replace('讲解质量：看真实回答，再选规则', '快速核查：修订应用与实际原文对照')
    html = html.replace('原有规则、简短基线、修订规则，以及三种展开方式的实际对照。', '保留实际原稿、核查输出及人工评语，检查哪些地方真的改变了。')
    html = html.replace("row.seconds+'秒 · 正文 '+row.output_chars+'字符 · 提示 '+row.input_chars+'字符'", 'row.metrics')
    html = html.replace('核对实际请求、用量与原文指纹', '查看实际核查输入、报告与原文指纹')
    start = html.index('<div class="notice">')
    end = html.index('</div>', start) + len('</div>')
    notice = ('本轮新增6次真实DeepSeek快速核查，使用3份之前保存的回答；共9个原样展示条目。'
        '密钥、私有思考与真实学生资料不进入报告。每份每版本只抽样一次，人工评阅没有盲评；'
        '两轮均能找出已知的两处物理错误，不能宣称本轮修复让模型变聪明或让完整任务提速。'
        '本轮修复针对程序应用修订：同一问题的替换整组生效，冲突和定位失败保持提示，引用和来源位置受保护；'
        '相关缺陷用受控失败案例复现，未在这6次返回中自然出现。局部替换没有再次独立模型复核，'
        '没有自动加审查轮次。原稿及核查本身都可能有漏检，不能作为未经核对的教材。')
    html = html[:start] + '<div class="notice">' + notice + '</div>' + html[end:]
    target = target_folder / '快速核查与修订实际对照.html'
    target.write_text(html, encoding='utf-8')
    (target_folder / '人工复核与统计.json').write_text(json.dumps({'new_actual_audit_calls': audit_calls,
        'displayed_items': payload['count'], 'groups': len(groups), 'original_answers_reused': 3,
        'private_reasoning_included': False, 'report_model_calls': 0, 'inspections': inspections}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(target)


if __name__ == '__main__': build()
