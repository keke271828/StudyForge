"""Inspectable verbatim follow-ups, with independent notes on remaining errors."""
import base64
import hashlib
import json
import re

from scripts.build_teaching_comparison import ROOT, TEMPLATE, inline_script
from scripts.eval_homework_followup import CASES


def build():
    folder = ROOT/'build/homework-followup-real-20261014-1'
    target_folder = ROOT/'build/homework-followup-20261014'
    target_folder.mkdir(parents=True, exist_ok=True)
    notes = {
        ('epsilon', 'link_only'): '开区间不含端点的解释成立，未读到原作答仍给出一份较长的通用证明，并把数列记号换成函数记号。数学主线可用，但不能据此声称核对了学生那道题或原作答。',
        ('epsilon', 'read_feedback'): '实际先调用按题回看，引用原作答“必须严格小于”的具体分岔，用原反馈中的开区间例子解释端点；说明更小正半径也可以。更贴近当前问题，但末句“下意识把端点算进去”仍只是对直觉的推测，不能记录成已证错因。',
        ('causal', 'link_only'): '调用两次学习画像查询，但画像中没有题干，随后坦诚无法指认本次错误并要求重贴。没有冒充已读批改；通用补充“效应估计值和方向一般还在”缺少足够依据，不能当成当前实验结论。',
        ('causal', 'read_feedback'): '实际读取了题干、作答和已交付批改，准确指出把随机提醒换成实际记笔记，保留了随机分配效应的价值。仍有两处不严谨：实际行为组的自选择，与随机分配组之间的行为比例差不能混为一谈；有未排除直接路径时，不能笼统说不遵从会使行为效应估计偏小。新增通道修复信息可达性，不足以保证模型的所有延伸正确。',
    }
    rows = json.loads((folder/'results.json').read_text(encoding='utf-8'))
    entries, failures = [], []
    for row in rows:
        if row['status'] != 'completed': failures.append(row); continue
        path = folder/row['answer_file']; text = path.read_bytes().decode('utf-8')
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest != row['answer_sha256']: raise ValueError('Model output changed.')
        requests = json.loads((folder/(row['case']+'-'+row['arm']+'-requests.json')).read_text(encoding='utf-8'))
        entries.append({'case': row['case'], 'arm': row['arm'], 'label': '仅下载链接' if row['arm']=='link_only' else '按题读取已交付反馈',
            'text': text, 'sha256': digest, 'output': str(path), 'review': notes[(row['case'], row['arm'])],
            'metrics': f"{row['seconds']}秒 · {row['characters']}字符 · {row['model_requests']}次模型请求 · deepseek-flash / high",
            'request': {'actual_call': row, 'public_requests': requests, 'private_reasoning_included': False}})
    groups = [{'case': key, 'title': case['title'], 'round': '同一教学规则，改变已交付反馈是否可读',
        'question': case['followup'], 'source': '合成题目：\n'+case['question']+'\n\n模拟学生作答：\n'+case['answer']+
            '\n\n预先提供的批改解释（并非本轮AI真实评分）：\n'+case['explanation'],
        'rows': sorted([entry for entry in entries if entry['case']==key], key=lambda row: row['arm'])} for key, case in CASES.items()]
    payload = {'groups': groups, 'count': len(entries), 'failures': failures}
    assets = ROOT/'web/vendor'
    css = (assets/'katex.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(fonts/([^)]*\.woff2)\)', lambda m: 'url(data:font/woff2;base64,'+base64.b64encode((assets/'fonts'/m[1]).read_bytes()).decode()+')', css)
    css = re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)', '', css)
    libraries = '\n'.join(inline_script((assets/name).read_text(encoding='utf-8')) for name in ('marked.js','purify.js','katex.js'))
    html = TEMPLATE.replace('__KATEX_CSS__', css).replace('__PAYLOAD__', json.dumps(payload, ensure_ascii=False).replace('<','\\u003c'))
    html = html.replace('__LIBRARIES__', libraries).replace('__RENDERER__', inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    html = html.replace('讲解质量：看真实回答，再选规则', '错题追问：导师能否读到你的具体作答')
    html = html.replace('原有规则、简短基线、修订规则，以及三种展开方式的实际对照。', '修复信息断点，逐份检查模型回答中仍未成立的判断。')
    html = html.replace("row.seconds+'秒 · 正文 '+row.output_chars+'字符 · 提示 '+row.input_chars+'字符'", 'row.metrics')
    html = html.replace('核对实际请求、用量与原文指纹', '查看公开请求、工具结果与正文指纹')
    start = html.index('<div class="notice">'); end = html.index('</div>', start)+len('</div>')
    notice = ('两道合成题、每臂一次，得到4份完整DeepSeek回答，共7次实际模型请求。'
        '两臂教学规则一致；对照臂移除新增的作业目录与按题读取工具，仅保留下载链接和学习画像工具，'
        '属于信息通道消融，不是完整旧版软件或网页端重放。批改和错因是试验预先提供的数据，不代表本轮真实AI评分通过。'
        '新通道两次均实际读取对应题目；旧因果样例两次查询画像后仍缺少题干。'
        '数学追问更贴近原作答，因果追问也更具体，但仍出现不受题干支持的补充判断，已单独指出。'
        '这些小样本未盲评、未重复取样，不证明全学科教学质量或普遍提速。只发布最终回答与公开工具输入，不含私有思考和密钥。')
    html = html[:start]+'<div class="notice">'+notice+'</div>'+html[end:]
    target = target_folder/'错题追问与批改衔接实际对照.html'
    target.write_text(html, encoding='utf-8')
    (target_folder/'人工复核与统计.json').write_text(json.dumps({'completed_answers': len(entries),
        'actual_model_requests': sum(row['model_requests'] for row in rows), 'failures': failures,
        'feedback_tool_calls': 2, 'private_reasoning_included': False,
        'notes': [{'case': entry['case'], 'arm': entry['arm'], 'review': entry['review']} for entry in entries]}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(target)


if __name__ == '__main__': build()
