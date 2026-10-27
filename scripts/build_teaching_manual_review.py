"""Offline comparison of pasted website finals and actual tutor API finals.

Reuses the local lesson renderer. Original responses are never rewritten;
private reasoning, credentials and automatically patched suggestions are absent.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

from scripts.build_teaching_comparison import ROOT, TEMPLATE, inline_script

B = ROOT / 'build'


def software(directory, case, label, note):
    report = json.loads((B / directory / 'report.json').read_text(encoding='utf-8'))
    row = next(r for r in report['results'] if r['case'] == case and r['status'] == 'completed')
    output = B / directory / row['answer_file']
    requests = json.loads((B / directory / row['request_file']).read_text(encoding='utf-8'))
    text = output.read_bytes().decode('utf-8')
    first_request = requests[0]
    return {
        'case': case, 'arm': directory, 'label': label, 'text': text,
        'output': str(output), 'sha256': hashlib.sha256(text.encode()).hexdigest(),
        'metrics': f"软件 · {row['elapsed_seconds']} 秒 · 首字 {row['first_visible_seconds']} 秒 · 正文 {row['answer_chars']} 字符",
        'request': requests, 'response_model': first_request.get('response_models'),
        'usage': first_request.get('usage'), 'review': note,
    }


def website(path, case, note, *, plain=False):
    output = B / path
    text = output.read_bytes().decode('utf-8')
    return {
        'case': case, 'arm': 'website', 'label': 'DeepSeek 网页（用户复制的最终回答）',
        'text': text, 'output': str(output), 'sha256': hashlib.sha256(text.encode()).hexdigest(),
        'metrics': '网页 · 未计时 · 只评最终正文 · 模型与开关由用户报告',
        'request': {'basis': '用户复制；本机浏览器未读取。V4.1 Flash、深度思考开启；用户最近报告未联网搜索。'},
        'response_model': None, 'usage': None, 'review': note, 'render_plain': plain,
    }


def build(output):
    s = software
    w = website
    groups = [
        {'case': 'cauchy', 'title': '柯西不等式：为什么构造含 t 的平方和',
         'question_file': 'teaching-natural-comparison-20261010-1/cauchy-question.txt',
         'rows': [
             w('teaching-natural-comparison-20261010-1/cauchy-web-final-original.txt', 'cauchy',
               '主线较集中；除法与等号讨论需要继续限定非零向量。复制出的重复公式与换行按原样展示，不以复制排版评模型优劣。思考过程未包含在此文件中。', plain=True),
             s('teaching-natural-comparison-20261010-1', 'cauchy', '软件：最初规则',
               '动机与数值比较有用；几何等价链漏掉零向量边界，补充优化漏掉退化条件，扩展过多。'),
             s('teaching-natural-minimal-20261010-1', 'cauchy', 'API：简短提示词基线',
               '开头直接，但同一行顶点表达式丢失负号，不能因更快就采用；此基线没有实际代理环境，不能单独归因于提示词。'),
             s('teaching-natural-compact-20261010-1', 'cauchy', '软件：精简共用规则',
               '主要系数匹配与退化处理改善，仍有非必要的缩放优化和扩展；不是已经通过所有边界的教材定稿。'),
         ]},
        {'case': 'cauchy_followup', 'title': '数学追问：取 t=1 已有三个量，为什么仍不够',
         'question_file': 'teaching-natural-followup-20261010-1/cauchy-question.txt',
         'rows': [
             w('teaching-natural-followup-20261010-1/cauchy-web-final-original.md', 'cauchy_followup',
               '本组优先：直接说明弱界与目标界，并给50.5对10的具体比较。“不能推出判别式非负”应为“不能推出判别式非正”；几何除法仍需非零条件。'),
             s('teaching-natural-followup-20261010-1', 'cauchy', '软件：原始追问',
               '出现错误理由：判别式并非只有“对所有t”时才有定义；依赖系数的单点代入可以证明目标。'),
             s('teaching-natural-compact-followup-20261010-1', 'cauchy', '软件：精简后的追问',
               '弱界与目标界对比改善；仍错误地把两种最优化参数说成相等，并把充分的整族非负性说成必须扫遍所有t，不能发布为正确定稿。'),
         ]},
        {'case': 'gauss', 'title': '高斯定律：净电荷零能否推出电场处处零',
         'question_file': 'teaching-natural-final-gauss-20261010-1/gauss-question.txt',
         'rows': [
             w('teaching-natural-revised-gauss-20261010-1/gauss-web-final-original.md', 'gauss',
               '主线与外部点电荷反例准确；微分形式、拉普拉斯方程和导体空腔属于更深延伸，应视前置知识决定是否继续。'),
             s('teaching-natural-revised-gauss-20261010-1', 'gauss', '软件：增加条件提醒',
               '主线正确，但“偶极子都在球内，所以没有场线穿过球面”错误，已用库仑定律独立反例核对。'),
             s('teaching-natural-compact-gauss-20261010-1', 'gauss', '软件：精简共用规则',
               '主要解释与反例连贯，未重复前一份的场线错误；严格全空间均匀场应作为理想化场，不声称由有限远处电荷在全空间精确产生。'),
             s('teaching-natural-final-gauss-20261010-1', 'gauss', '软件：条件式风格复测',
               '复测未过关：静态均匀电场可以是静电场；等量异号点电荷中点电场非零。把对称性说成唯一必要路径也过强。提示词通过软件测试不保证本份内容正确。'),
             s('teaching-natural-candidate-gauss-20261010-1', 'gauss', '实验：进一步缩短规则',
               '未采用候选：净通量主线有帮助，但补充扩展仍不够克制，“必须对称性”的总结过强。场线成环需要区分静电场与一般时变电场，不能当作所有场的直观说明。'),
             s('teaching-natural-lite-gauss-20261010-2', 'gauss', '实验：极短规则复测（未采用）',
               '主要解释正确，篇幅更少，但“无净电荷区域场线不产生/终止”误把净零当作局部无电荷；sin(x)也并非每点都非零。两处与前后正确表述不一致，仍未通过。'),
         ]},
        {'case': 'notes_causality', 'title': '社会科学：两万人的显著关联是否证明因果',
         'question_file': 'teaching-natural-final-causal-20261010-1/notes_causality-question.txt',
         'rows': [
             w('teaching-natural-final-causal-20261010-1/notes_causality-web-final-original.md', 'notes_causality',
               '本组更清楚：先分随机波动与系统偏差，再说明可比性。仍需限定：大样本提高精度依赖采样/误差结构；无法观察个体两种反事实不等于无法估计平均因果效应；随机干预首先识别干预效果，而非一概识别实际行为效果。'),
             s('teaching-natural-final-causal-20261010-1', 'notes_causality', '软件：跨学科自然问题',
               '主结论正确，但新记号与公式过多；随机鼓励仅随机化鼓励，不能据此宣称实际记笔记T已随机化。“唯一的直接解法”过强。'),
             s('teaching-natural-lite-notes_causality-20261010-2', 'notes_causality', '实验：极短规则复测（未采用）',
               '开始用具体比较解释了问题，但又引入错的因果分解：前面tau定义为总体平均因果效应，后面组间差分解一般需要处理组平均效应。大样本也不会完全“排除”抽样偶然。更短仍未通过内容验收。'),
         ]},
    ]
    for group in groups:
        group['round'] = '人工最终回答对照'
        group['question'] = (B / group.pop('question_file')).read_text(encoding='utf-8')
        group['source'] = '本组未上传资料，问题文本如上。网页端由用户新建或继续对话后复制；软件端使用隔离数据库，不修改真实画像。各轮不是多次重复抽样。'
        group['rows'].sort(key=lambda row: row['sha256'])
    failures = []
    for name in ('teaching-natural-candidate-notes_causality-20261010-1',
                 'teaching-natural-lite-gauss-20261010-1', 'teaching-natural-lite-notes_causality-20261010-1'):
        packet = json.loads((B / name / 'report.json').read_text(encoding='utf-8'))
        failures.extend({'round': name, **r} for r in packet['results'] if r['status'] != 'completed')
    payload = json.dumps({'groups': groups, 'count': sum(len(g['rows']) for g in groups), 'failures': failures}, ensure_ascii=False).replace('<', '\\u003c')
    assets = ROOT / 'web/vendor'
    css = (assets / 'katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,' + base64.b64encode((assets / 'fonts' / m[1]).read_bytes()).decode() + ')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    libraries = '\n'.join(inline_script((assets / f).read_text(encoding='utf-8')) for f in ('marked.js', 'purify.js', 'katex.js'))
    renderer = inline_script((ROOT / 'web/lesson_render.js').read_text(encoding='utf-8'))
    html = TEMPLATE.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', payload).replace('__LIBRARIES__', libraries).replace('__RENDERER__', renderer)
    html = html.replace('原有规则、简短基线、修订规则，以及三种展开方式的实际对照。', '用户复制的 DeepSeek 网页最终回答，与软件真实聊天入口回答的对照。')
    start = html.index('<div class="notice">')
    end = html.index('</div>', start) + len('</div>')
    html = html[:start] + '<div class="notice">网页文本由用户复制，仅评最终回答；没有访问网站内部配置，没有网页耗时。DeepSeek 官方当前将 deepseek-flash 标为 V4.1 Flash，仍不能证明两端服务配置完全相同。软件为 high、精学、直观与专业并重；保留真实代理环境，未启用网页、文件等操作工具，但画像读取工具仍可用，画像为空。各份原样保留，包含不合格样例；不要把它们当成已审定教材。近期三次 API 连接超时不计作教学质量样本。软件样例采集于本次教学设置切换修复之前；修复不改写原回答，也不代表这些内容错误已消失。</div>' + html[end:]
    html = html.replace("row.seconds+'秒 · 正文 '+row.output_chars+'字符 · 提示 '+row.input_chars+'字符'", 'row.metrics')
    html = html.replace('renderLessonText(body,row.text);', "if(row.render_plain){body.append(element('pre','',row.text))}else{renderLessonText(body,row.text)}")
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding='utf-8')
    manifest = {'samples': sum(len(g['rows']) for g in groups), 'groups': len(groups),
                'website_finals': 4, 'failed_requests': len(failures), 'model_calls': 0,
                'private_reasoning_included': False, 'output': str(target),
                'capture_stage': '教学设置签名修复前；原回答未被改写',
                'scope': '原始最终回答、人工检查、离线显示；不代表已解决全部教学问题。'}
    target.with_suffix('.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    build(p.parse_args().output)
