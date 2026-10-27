"""Format contracts and static checks. Generated programs are never executed here."""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import PurePosixPath


def json_object(text):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*\n|\n```\s*$', '', text)
    value = json.loads(text)
    if not isinstance(value, dict): raise ValueError('格式内容必须是JSON对象')
    return value


def cards(value, max_count=300, max_question=400):
    items = value.get('cards')
    if not isinstance(items, list) or not 1 <= len(items) <= max_count:
        raise ValueError(f'记忆卡片须包含1—{max_count}张卡片')
    result = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict): raise ValueError(f'第{index}张卡片内容无效')
        row = {}
        for key, limit in [('question', max_question), ('answer', 2000), ('source', 1000)]:
            text = item.get(key, '' if key == 'source' else None)
            if not isinstance(text, str) or (key != 'source' and not text.strip()) or len(text) > limit:
                raise ValueError(f'第{index}张卡片的{key}为空或过长；请拆成聚焦一个问题的卡片')
            row[key] = text.strip()
        result.append(row)
    return result


def student_cards(questions):
    """Question-only exercise export; never receives private solutions."""
    return json.dumps({'purpose':'student_exercises','cards':[
        {'question':str(q['question']),'answer':'尚未显示解析。请在学习软件中完成整套题并提交，再查看批改与解析。',
         'source':f'配套习题 · 原题{index}'} for index,q in enumerate(questions,1)]},ensure_ascii=False)


def bundle_files(value):
    items = value.get('files')
    if not isinstance(items, list) or not 1 <= len(items) <= 40:
        raise ValueError('代码包须包含1—40个文件')
    result, names, size = [], set(), 0
    for item in items:
        if not isinstance(item, dict): raise ValueError('代码包文件内容无效')
        name, content = item.get('path'), item.get('content')
        if not isinstance(name, str) or not isinstance(content, str): raise ValueError('代码包需要文件名和文本内容')
        parts = PurePosixPath(name).parts
        if (not parts or name.startswith('/') or '\\' in name or any(p in ('.', '..') for p in name.split('/'))
                or any(re.search(r'[<>:"|?*\x00-\x1f]', p) or p.endswith((' ', '.')) or
                       re.fullmatch(r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p) for p in parts)):
            raise ValueError('代码包文件名必须是可在Windows打开的相对路径')
        if len(name) > 180 or name.casefold() in names: raise ValueError('代码包文件名过长或重复')
        names.add(name.casefold()); size += len(content)
        if size > 2_000_000: raise ValueError('代码包文本过大')
        result.append({'path': name, 'content': content})
        if PurePosixPath(name).suffix.lower()=='.m':
            stem=PurePosixPath(name).stem;entry=matlab_entry_name(content)
            if not matlab_identifier(stem) or (entry and entry!=stem):
                raise ValueError('MATLAB文件名须为合法标识符，函数或类文件名须与首个函数或类名一致')
    if any(other.startswith(name+'/') for name in names for other in names):
        raise ValueError('代码包中同一路径不能同时作为文件和目录')
    if not any(PurePosixPath(x['path']).suffix.lower() in {'.py', '.js', '.ts', '.cpp', '.m', '.wl'} for x in result):
        raise ValueError('代码包没有程序或数学模型文件，请选择文档格式')
    return result


def matlab_identifier(name):
    keywords={'break','case','catch','classdef','continue','else','elseif','end','for','function','global',
              'if','otherwise','parfor','persistent','return','spmd','switch','try','while'}
    return bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,62}',name)) and name not in keywords


def matlab_entry_name(code):
    """Only a first function/class fixes the filename; local script functions do not."""
    comment=False
    for raw in code.splitlines():
        line=raw.strip().lstrip('\ufeff')
        if line=='%{': comment=True;continue
        if line=='%}': comment=False;continue
        if comment or not line or line.startswith('%'): continue
        line=line.split('%',1)[0].rstrip()
        if re.match(r'^function\b',line):
            match=re.match(r'^function\s*(?:(?:\[[^\]]*\]|[A-Za-z]\w*)\s*=\s*)?([A-Za-z]\w*)\s*(?:\(|$)',line)
        elif re.match(r'^classdef\b',line):
            match=re.match(r'^classdef\s*(?:\([^)]*\)\s*)?([A-Za-z]\w*)',line)
        else: return None
        if not match or not matlab_identifier(match[1]): raise ValueError('无法识别MATLAB首个函数或类名；请采用合法英文标识符')
        return match[1]
    return None


def static_check(name, code):
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == '.py':
        ast.parse(code, filename=name)
        return {'file': name, 'syntax_checked': True, 'detail': 'Python语法通过；未执行，依赖、数值结果和适用性未验证'}
    if suffix == '.js' and (binary := shutil.which('node')):
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        result = subprocess.run([binary, '--check', '--input-type=module'], input=code, capture_output=True,
                                text=True, encoding='utf-8', timeout=15, creationflags=flags)
        if result.returncode: raise ValueError('JavaScript语法检查失败：' + result.stderr[:800])
        return {'file': name, 'syntax_checked': True, 'detail': 'JavaScript语法通过；未执行，模块、依赖和结果未验证'}
    labels = {'.m': 'MATLAB', '.wl': 'Mathematica', '.cpp': 'C++', '.ts': 'TypeScript', '.js': 'JavaScript'}
    if suffix in labels:
        return {'file': name, 'syntax_checked': False, 'detail': f'{labels[suffix]}文件已写入；尚未在目标环境编译或执行验证'}
    return None


async def shape_content(client, document, fmt, *, learning_mode='deep', language='zh', requirements='', explanation_style='clear'):
    """Use the same teaching client; extra calls only for requested card/bundle formats."""
    if fmt not in ('apkg', 'zip'): return document, 0
    from .ai import explanation_batches, complete_json
    from .teaching import TEACHER_PERSONA
    from .learning_modes import mode_policy
    from .teaching_styles import style_policy, language_policy
    batches = explanation_batches(document, max_chars=48000)
    if fmt == 'zip': batches = [document] if len(document) <= 48000 else batches
    collected = []
    requests=0
    def repaired():
        nonlocal requests
        requests+=1
    for index, part in enumerate(batches, 1):
        if fmt == 'apkg':
            system = ('【Anki格式整理】将已经生成的讲解改成用于主动回忆的卡片。只返回JSON对象'
                      '{"cards":[{"question":"...","answer":"...","source":"..."}]}。'
                      '每张只问一个明确知识点，题面包含必要对象与条件；答案简短准确，不把整章塞到背面。'
                      '分别提问概念、方法选择理由、关键推理和适用边界；不要仅用章节名当问题。'
                      '一张承载过多内容时拆分，不用模糊代词，不在题面泄露答案。数学用标准LaTeX。'
                      '保留对应原文定位或实际引用的链接；只整理给出的讲解，不补造事实、历史和引用。'
                      'source缺失时留空，并在答案注明来源待核对。不出测验，不使用私有参考解。'
                      '问题不超过400字符，答案不超过2000字符，每批至多300张。')
        else:
            system = ('【代码包格式整理】依据本次讲解和学生的编程语言要求交付多文件程序或数学模型，'
                      '不要默认只用Python。只返回JSON对象{"files":[{"path":"相对路径","content":"文件全文"}]}。'
                      '包含至少一个程序，参数、单位、依赖和运行方法在注释或README中说明，附适用条件和示例。'
                      '不得伪造执行结果，明确尚未运行。文件名须可在Windows使用；不输出绝对路径、父目录或二进制文件。'
                      '每批至多40个文件；多部分时使用互不冲突的文件名，保持引用一致。不输出无关程序。')
            system+='MATLAB文件使用合法英文标识符命名；首个函数或类名须与文件名一致。'
        requests+=1
        response = await complete_json(client,TEACHER_PERSONA+system+mode_policy(learning_mode)+style_policy(explanation_style)+language_policy(language)+
                    '语言和风格规则用于卡片文本、代码注释及README；仅返回一个JSON对象，键名、代码标识符与文件路径不翻译。',
                    f'沿用当前学习对话。输出语言：{language}；学生要求：{requirements}\n'
                    f'只整理本次已生成的第{index}/{len(batches)}部分讲解，不能把学生误解或旧回答当作证据：\n{part}',
                    validate=cards if fmt=='apkg' else bundle_files,on_repair=repaired)
        collected.extend(cards(response) if fmt == 'apkg' else bundle_files(response))
    key = 'cards' if fmt == 'apkg' else 'files'
    if fmt == 'apkg':
        # Each batch is bounded; the combined deck can legitimately be larger.
        unique = {(x['question'], x['answer'], x['source']): x for x in collected}
        collected = list(unique.values())
    else:
        collected = bundle_files({'files': collected})
    return json.dumps({key: collected}, ensure_ascii=False), requests


def inspection(path):
    """Report actual checks only, never infer execution from a model claim."""
    import zipfile
    suffix = path.suffix.lower()
    result = {'format': suffix.lstrip('.'), 'executed': False, 'checks': [], 'format_model_requests': 0}
    if suffix in {'.py', '.js', '.ts', '.cpp', '.m', '.wl'}:
        result['checks'] = [static_check(path.name, path.read_text(encoding='utf-8'))]
        if suffix=='.m':
            result['matlab_entry_name']=matlab_entry_name(path.read_text(encoding='utf-8'))
            result['detail']='MATLAB文件名按脚本或首个函数/类名组织；成果标签可中文，代码尚未执行验证'
    elif suffix == '.ipynb':
        notebook = json.loads(path.read_text(encoding='utf-8'))
        for i, cell in enumerate(notebook['cells']):
            if cell['cell_type'] == 'code':
                result['checks'].append(static_check(f'cell-{i}.py', ''.join(cell['source'])))
        result['detail'] = 'Notebook结构可读取；代码单元未执行，输出为空'
    elif suffix == '.zip':
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                row = static_check(name, archive.read(name).decode('utf-8'))
                if row: result['checks'].append(row)
        result['detail'] = '代码包可读取；目标环境、依赖与各文件间协作未执行验证'
    elif suffix == '.apkg':
        result['detail'] = '记忆卡组已生成；卡片取舍不能替代完整讲解，不证明已掌握'
    else:
        result['detail'] = '文件已导出；实际阅读效果请在对应软件验收'
    return result
