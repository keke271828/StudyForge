"""Verbatim local view of the bounded summary experiment and its limitations."""
import base64
import hashlib
import json
import re

from scripts.build_teaching_comparison import ROOT, TEMPLATE, inline_script
from scripts.eval_summary_cautions import CASES


def build():
    base = ROOT / 'build/summary-cautions-real-20261014-1'
    followup = ROOT / 'build/summary-cautions-real-20261014-2'
    target_folder = ROOT / 'build/summary-cautions-20261014'
    target_folder.mkdir(parents=True, exist_ok=True)
    notes = {
        ('math', 'omitted_detail', False): '识别到具体核查内容缺失，没有编造n的门槛，也没有把尾部估计扩大为所有项；但无法告诉学生准确的n>100边界。主线重复较多，还复述了试验占位符与记录计数。',
        ('math', 'with_detail', False): '把n>100与估计及后续使用连在一起，明确前100项不受此估计约束，未凭空补造这些项的数值。更具体且较凝练；单次样本不证明普遍质量或速度优势。',
        ('causal', 'omitted_detail', False): '没有编造遗漏的核查内容，保留平均分差异。但“不能当作提醒导致提高的因果定论”没有区分有效随机分配可估计的提醒分配效应和记笔记行为效应，表达过于保守。',
        ('causal', 'with_detail', False): '保留了随机分配对象、不遵从与其他路径，正确限制“记笔记本身已证有效”。结尾“只能停留在关联”却可能把这一局部限制扩大到随机提醒实验整体，不能评为完全合格的因果说明。',
        ('causal', 'with_detail', True): '补测不再明确说只能得到关联，正确限制的是记笔记行为效应，未把疑点说成已经排除。仍只保留了组间差异描述，没有展开在有效随机分配等条件下可估计的提醒分配效应；内容有重复。一次补测不能证明稳定修复了模型的因果推理。',
    }
    entries, failures = [], []
    for folder in (base, followup):
        requests = json.loads((folder / 'requests.json').read_text(encoding='utf-8'))
        for row in json.loads((folder / 'results.json').read_text(encoding='utf-8')):
            if row['status'] != 'completed':
                failures.append({'round': folder.name, **row})
                continue
            path = folder / row['answer_file']
            text = path.read_bytes().decode('utf-8')
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest != row['answer_sha256']: raise ValueError('Output fingerprint changed.')
            follow = folder == followup
            key = (row['case'], row['arm'], follow)
            label = ('补测：限定疑点的作用范围' if follow else '保留具体核查记录' if row['arm']=='with_detail' else '对照：不提供核查记录的具体正文')
            entries.append({'case': row['case'], 'arm': folder.name+':'+row['case']+':'+row['arm'], 'label': label,
                'text': text, 'sha256': digest, 'output': str(path), 'review': notes[key],
                'metrics': f"{row['seconds']}秒 · {row['characters']}字符 · deepseek-flash / high · 工具关闭",
                'request': {'frozen_input': requests[row['case']+':'+row['arm']], 'actual_call': row}})
    groups = [{'case': name, 'title': case['title'], 'round': '真实模型输入记录消融',
        'question': '只总结两部分已写讲解的主线、联系与成立边界；不补造缺失细节，不出题。',
        'source': '合成章节小结：\n'+'\n'.join(case['recaps'])+'\n\n第一部分的核查记录：\n'+case['detail']+
            '\n\n试验另加重复的已写段落，触发长文辅助输入节选；不是用户教材或视频。',
        'rows': [entry for entry in entries if entry['case']==name]} for name, case in CASES.items()]
    payload = {'groups': groups, 'count': len(entries), 'failures': failures}
    assets = ROOT / 'web/vendor'
    css = (assets / 'katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,'+
        base64.b64encode((assets / 'fonts' / m[1]).read_bytes()).decode()+')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    libraries = '\n'.join(inline_script((assets / file).read_text(encoding='utf-8')) for file in ('marked.js','purify.js','katex.js'))
    html = TEMPLATE.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', json.dumps(payload, ensure_ascii=False).replace('<','\\u003c'))
    html = html.replace('__LIBRARIES__', libraries).replace('__RENDERER__', inline_script((ROOT / 'web/lesson_render.js').read_text(encoding='utf-8')))
    html = html.replace('讲解质量：看真实回答，再选规则', '长文总结：保留核查记录与结论范围')
    html = html.replace('原有规则、简短基线、修订规则，以及三种展开方式的实际对照。', '同一模型的实际返回，检查证据缺失、条件保留与过度保守。')
    html = html.replace("row.seconds+'秒 · 正文 '+row.output_chars+'字符 · 提示 '+row.input_chars+'字符'", 'row.metrics')
    html = html.replace('核对实际请求、用量与原文指纹', '查看冻结输入、实际调用与原文指纹')
    start = html.index('<div class="notice">'); end = html.index('</div>', start)+len('</div>')
    notice = ('5次实际DeepSeek返回原样保存，不含私有思考、密钥或真实学习记录。前4次是两份合成材料各两臂：'
        '两臂使用相同的当前总结提示，只把具体核查正文替换为缺失占位，考察具体证据能否进入总结；'
        '这不是旧版本软件的完整回放。消融臂保留了相同的记录计数，计数不能当成具体证据已经传入的验收。'
        '第5次是在因果样例暴露过度保守后，增加通用的“疑点只限制相应断言”说明，再单独补测。'
        '每臂一次，未随机排序、未盲评；耗时差异不能证明完整生成普遍提速。'
        '此页呈现模型原始总结，没有插入软件在实际成果中自动保留的核查提示；人工评语独立展示，仍可能不完整。'
        '数学边界在保留记录后更具体，社会科学总结仍有保守和重复，不宣称所有教学问题解决。')
    html = html[:start]+'<div class="notice">'+notice+'</div>'+html[end:]
    target = target_folder / '长文总结与核查记录实际对照.html'
    target.write_text(html, encoding='utf-8')
    (target_folder / '人工复核与统计.json').write_text(json.dumps({'actual_calls': len(entries)+len(failures),
        'successful_calls': len(entries), 'failures': failures, 'displayed_samples': len(entries), 'groups': len(groups),
        'new_report_model_calls': 0, 'private_reasoning_included': False,
        'inspection': [{'label': entry['label'], 'case': entry['case'], 'note': entry['review']} for entry in entries]}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(target)


if __name__ == '__main__': build()
