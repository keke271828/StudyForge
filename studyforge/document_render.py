"""Markdown and mathematics rendering shared by Word and PDF exports."""
from __future__ import annotations

import hashlib
import html
import io
import re
import threading
import warnings
from pathlib import Path

from .config import temp_dir

_math_lock = threading.Lock()
EXPLANATION_COLOR = '164B63'
SOURCE_COLOR = '374151'
EXPLANATION_FONT = 'Microsoft YaHei'
SOURCE_FONT = 'SimSun'
INLINE = re.compile(r'(\$[^$\n]+\$|\\\(.*?\\\)|\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^\)]+\))')
MATH_OR_CODE = re.compile(r'(\$[^$\n]+\$|\\\(.*?\\\)|`[^`]+`)')


def inline_parts(text: str):
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith('$') and part.endswith('$'):
            yield 'math', part[1:-1]
        elif part.startswith('\\(') and part.endswith('\\)'):
            yield 'math', part[2:-2]
        elif part.startswith('**') and part.endswith('**'):
            # Emphasis wraps content; it must not turn an equation into literal
            # LaTeX. Keep native math tokens for all downstream exporters.
            for kind, value in inline_parts(part[2:-2]):
                yield ('bold' if kind in ('text', 'bold') else kind), value
        elif part.startswith('`') and part.endswith('`'):
            yield 'code', part[1:-1]
        elif re.match(r'^\[.+\]\(.+\)$', part):
            match = re.match(r'^\[(.+)\]\((.+)\)$', part)
            yield 'text', f'{match[1]} ({match[2]})'
        else:
            yield 'text', part


def owned_image(text: str):
    """Resolve an actual generated image; never fetch a Markdown URL at export."""
    match = re.fullmatch(r'!\[([^\]\n]*)\]\(/api/agent/assets/([a-f0-9]{32})/image\)', text.strip())
    if not match: return None
    from .db import one
    from .config import artifacts_dir
    row = one('SELECT path FROM agent_assets WHERE id=?', (match[2],))
    if not row: raise ValueError('讲解引用的生成图片不存在，请重新生成图片后再导出')
    path = Path(row['path']).resolve()
    if not path.is_relative_to(artifacts_dir()) or not path.is_file():
        raise ValueError('讲解引用的生成图片已删除或位置无效')
    return path, match[1]


def image_size(path, max_width, max_height):
    from PIL import Image
    with Image.open(path) as image: width, height = image.size
    scale = min(max_width / width, max_height / height)
    return width * scale, height * scale


def table_row(line):
    protected=set()
    for match in MATH_OR_CODE.finditer(line):
        protected.update(range(match.start(),match.end()))
    cells,current=[],''
    index=0
    while index<len(line):
        char=line[index]
        if char=='\\' and index not in protected and line[index:index+2]=='\\|':
            current+='|';index+=2;continue
        if char=='|' and index not in protected:
            cells.append(current.strip());current=''
        else: current+=char
        index+=1
    cells.append(current.strip())
    if cells and not cells[0]: cells=cells[1:]
    if cells and not cells[-1]: cells=cells[:-1]
    return cells


def table_start(header, separator):
    cells, marks = table_row(header), table_row(separator)
    if not cells or len(cells) != len(marks): return False
    if len(cells) == 1 and not (header.strip().startswith('|') and header.strip().endswith('|')):
        return False
    return all(re.fullmatch(r':?-{3,}:?', cell) for cell in marks)


def blocks(content: str, preserve_list_numbers: bool = False, *, parse_tables: bool = True):
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        value = lines[index].strip()
        index += 1
        if not value:
            continue
        if value.startswith('>'):
            quoted = [re.sub(r'^> ?', '', value)]
            while index < len(lines) and lines[index].strip().startswith('>'):
                quoted.append(re.sub(r'^> ?', '', lines[index].strip()))
                index += 1
            inner='\n'.join(quoted)
            if '$$' in inner or '\\[' in inner:
                for kind,item in blocks(inner, parse_tables=parse_tables):
                    if kind=='math': yield 'quote_math', item
                    elif kind=='heading': yield 'quote', '#'*item[0]+' '+item[1]
                    elif kind=='table': yield 'quote','\n'.join(' | '.join(row) for row in item)
                    else: yield 'quote',item
            else: yield 'quote',inner
        elif re.match(r'^(?:`{3,}|~{3,})',value):
            marker=re.match(r'^(`{3,}|~{3,})',value)[1]
            code = []
            while index < len(lines) and not re.fullmatch(re.escape(marker[0])+'{'+str(len(marker))+',}\\s*',lines[index].strip()):
                code.append(lines[index]); index += 1
            if index>=len(lines): raise ValueError('文档中的代码块缺少结束标记，已停止导出')
            index += 1
            yield 'code', '\n'.join(code)
        elif value.startswith(('$$','\\[')):
            close='$$' if value.startswith('$$') else '\\]'
            rest=value[2:];rows=[]
            while close not in rest:
                rows.append(rest)
                if index>=len(lines): raise ValueError('文档中的公式缺少结束标记，已停止导出')
                rest=lines[index];index+=1
            body,tail=rest.split(close,1);rows.append(body)
            yield 'math','\n'.join(rows).strip()
            if tail.strip(): yield 'paragraph',tail.strip()
        elif re.match(r'^#{1,6}\s', value):
            heading = re.match(r'^(#{1,6})\s+(.+)', value)
            yield 'heading', (len(heading[1]), heading[2])
        elif parse_tables and index < len(lines) and table_start(value, lines[index]):
            rows = [table_row(value)]
            index += 1
            while index < len(lines) and lines[index].strip():
                line = lines[index].strip()
                row = table_row(line)
                if not row or (len(row) == 1 and not (line.startswith('|') and line.endswith('|'))):
                    break
                rows.append(row); index += 1
            yield 'table', rows
        elif value.startswith(('- ', '* ')):
            yield 'bullet', value[2:]
        elif re.match(r'^\d+[.)]\s', value):
            yield 'number', value if preserve_list_numbers else re.sub(r'^\d+[.)]\s+', '', value)
        elif value in ('---', '***'):
            continue
        else:
            yield 'paragraph', value


def rich_html(content: str) -> str:
    """Safe, styled content for Anki and notebook markdown cells."""
    def inline(text):
        parts = []
        for kind, value in inline_parts(text):
            escaped = html.escape(value, quote=False).replace('\n', '<br/>')
            if kind == 'bold': escaped = f'<strong>{escaped}</strong>'
            elif kind == 'code': escaped = f'<code>{escaped}</code>'
            elif kind == 'math': escaped = r'\(' + escaped + r'\)'
            parts.append(escaped)
        return ''.join(parts)
    result = []
    for kind, value in blocks(content):
        if kind in ('quote','quote_math'):
            result.append(f'<blockquote style="font-family:SimSun,\'Times New Roman\',serif;color:#{SOURCE_COLOR};'
                          'background:#F3F5F7;border-left:3px solid #9BAAB8;padding:10px 14px;margin:12px 0;">'
                          + (r'\['+html.escape(value,quote=False)+r'\]' if kind=='quote_math' else inline(value)) + '</blockquote>')
        elif kind == 'heading':
            depth = min(value[0], 6)
            result.append(f'<h{depth}>' + inline(value[1]) + f'</h{depth}>')
        elif kind == 'math':
            result.append('<p>' + r'\[' + html.escape(value, quote=False) + r'\]' + '</p>')
        elif kind == 'code':
            result.append('<pre><code>' + html.escape(value) + '</code></pre>')
        elif kind == 'table':
            result.append('<table>' + ''.join('<tr>' + ''.join('<td>' + inline(cell) + '</td>' for cell in row) + '</tr>' for row in value) + '</table>')
        else:
            result.append('<p>' + ('• ' if kind == 'bullet' else '') + inline(value) + '</p>')
    return f'<div style="font-family:\'Microsoft YaHei\',Arial,sans-serif;color:#{EXPLANATION_COLOR};line-height:1.65;">' + '\n'.join(result) + '</div>'


def word_math(latex: str):
    from latex2mathml.converter import convert
    from lxml import etree
    from docx.oxml import OxmlElement

    def element(name, *children):
        root = OxmlElement('m:' + name)
        for child in children:
            root.append(child)
        return root

    def expression(node):
        kind = etree.QName(node).localname
        children = list(node)
        if kind in ('mi', 'mn', 'mo', 'mtext'):
            text = element('t'); text.text = node.text or ''
            run = element('r', text)
            variant = node.get('mathvariant')
            if (variant in ('normal','bold','bold-italic') or kind=='mtext' or
                    (kind=='mi' and len(text.text)>1 and variant!='italic')):
                style=element('sty')
                style.set('{http://schemas.openxmlformats.org/officeDocument/2006/math}val',
                          {'bold':'b','bold-italic':'bi'}.get(variant,'p'))
                run.insert(0,element('rPr',style))
            return [run]
        mappings = {'mfrac': ('f', ['num', 'den']), 'msup': ('sSup', ['e', 'sup']),
                    'msub': ('sSub', ['e', 'sub']), 'msubsup': ('sSubSup', ['e', 'sub', 'sup']),
                    'munder': ('sSub', ['e', 'sub']),
                    'munderover': ('sSubSup', ['e', 'sub', 'sup'])}
        if kind in mappings:
            tag, slots = mappings[kind]
            return [element(tag, *(element(slot, *expression(child)) for slot, child in zip(slots, children)))]
        if kind == 'mover':
            char = ''.join(children[1].itertext())
            if char in ('→', 'ˆ', '^', '˙', '¨', '~', '¯', '‾'):
                prop = element('chr'); prop.set('{http://schemas.openxmlformats.org/officeDocument/2006/math}val', char)
                return [element('acc', element('accPr', prop), element('e', *expression(children[0])))]
            return [element('sSup', element('e', *expression(children[0])), element('sup', *expression(children[1])))]
        if kind == 'msqrt':
            prop = element('degHide'); prop.set('{http://schemas.openxmlformats.org/officeDocument/2006/math}val', '1')
            return [element('rad', element('radPr', prop), element('deg'), element('e', *(x for c in children for x in expression(c))))]
        if kind == 'mroot':
            return [element('rad', element('deg', *expression(children[1])), element('e', *expression(children[0])))]
        if kind == 'mtable':
            return [element('m', *(element('mr', *(element('e', *expression(cell)) for cell in row)) for row in children))]
        if kind == 'mspace':
            text = element('t'); text.text = ' '
            return [element('r', text)]
        if kind == 'annotation':
            return []
        return [value for child in children for value in expression(child)]

    latex = re.sub(r'\\(begin|end)\{(?:aligned|align\*?|gathered)\}', r'\\\1{matrix}', latex)
    # Alignment markers are column separators only inside a supported table.
    markup = convert(latex)
    markup = re.sub(r'&(?!#\d+;|#x[0-9a-fA-F]+;|amp;|lt;|gt;|quot;|apos;)', '&amp;', markup)
    root = etree.fromstring(markup.encode('utf-8'))
    return element('oMath', *expression(root))


def mathtext_arguments(latex: str) -> str:
    """Add the braces MathText requires around legal single-token TeX arguments.

    TeX reads ``\\sqrt23`` as ``\\sqrt{2}3``, not ``\\sqrt{23}``.
    Read atoms (including nested macros) instead of guessing with a greedy regex.
    Unknown commands and ordinary symbols are preserved for renderer validation.
    """
    arity = {name: 1 for name in (
        'sqrt', 'mathbb', 'mathcal', 'mathscr', 'mathrm', 'mathit', 'mathbf',
        'mathsf', 'mathtt', 'overline', 'widehat', 'widetilde', 'hat', 'bar',
        'vec', 'dot', 'ddot', 'tilde', 'breve', 'check', 'acute', 'grave')}
    arity['frac'] = 2

    def sequence(index, closing=None):
        parts = []
        while index < len(latex):
            if closing and latex[index] == closing:
                return ''.join(parts), index + 1
            value, index = token(index)
            parts.append(value)
        if closing:
            raise ValueError('公式的分组缺少结束标记')
        return ''.join(parts), index

    def token(index):
        char = latex[index]
        if char == '{':
            inner, end = sequence(index + 1, '}')
            return '{' + inner + '}', end
        if char != '\\':
            return char, index + 1
        command = re.match(r'\\(?:[A-Za-z]+|.)', latex[index:])
        if not command:
            return char, index + 1
        value = command[0]
        end = index + len(value)
        name = value[1:]
        if name not in arity:
            return value, end
        if name == 'sqrt':
            look = end
            while look < len(latex) and latex[look].isspace():
                look += 1
            if look < len(latex) and latex[look] == '[':
                degree, end = sequence(look + 1, ']')
                value += '[' + degree + ']'
        for _ in range(arity[name]):
            while end < len(latex) and latex[end].isspace():
                end += 1
            if end >= len(latex) or latex[end] in '}]':
                raise ValueError('公式命令缺少参数：' + command[0])
            argument, end = token(end)
            value += argument if argument.startswith('{') else '{' + argument + '}'
        return value, end

    return sequence(0)[0]


def math_image(latex: str, color='19343d') -> Path:
    key = hashlib.sha256(('dpi300-v5:'+color+':' + latex).encode('utf-8')).hexdigest()
    path = temp_dir() / f'math-{key}.png'
    if path.exists():
        return path
    with _math_lock:
        from matplotlib.mathtext import math_to_image
        from matplotlib.font_manager import FontProperties
        from PIL import Image
        # Render multi-line aligned formulas row by row without displaying markup.
        clean = re.sub(r'\\(?:begin|end)\{(?:aligned|align\*?|gathered|equation\*?)\}', '', latex)
        clean = clean.replace('&', '').replace('\\displaystyle', '').strip()
        clean = clean.replace('\\tfrac', '\\frac').replace('\\dfrac', '\\frac')
        clean = re.sub(r'\\(le|ge)(?![A-Za-z])', lambda m:'\\'+m[1]+'q',clean)
        rows = re.split(r'\\\\(?:\[[^\]]*\])?', clean)
        images = []
        try:
            for row in rows:
                if not row.strip():
                    continue
                buffer = io.BytesIO()
                row = mathtext_arguments(re.sub(r'\s+', ' ', row).strip())
                with warnings.catch_warnings(record=True) as notices:
                    warnings.simplefilter('always')
                    math_to_image('$' + row + '$', buffer, prop=FontProperties(size=12), dpi=300, format='png', color='#'+color)
                if any('Glyph' in str(notice.message) and 'missing' in str(notice.message) for notice in notices):
                    raise ValueError('公式字体缺少必要字符')
                images.append(Image.open(buffer).convert('RGBA'))
        except (ValueError, RuntimeError) as exc:
            raise ValueError(f'无法排版公式：{latex[:120]}。请检查公式括号或命令；当前排版器不支持的公式可选择 Word 格式') from exc
        if not images:
            raise ValueError('公式内容为空')
        result = Image.new('RGBA', (max(im.width for im in images), sum(im.height for im in images) + 9 * (len(images) - 1)), 'white')
        top = 0
        for image in images:
            result.paste(image, (0, top), image); top += image.height + 9
        result.save(path)
    return path


def validate_document_text(content: str) -> None:
    invalid = re.search(r'[\ufffd\ud800-\udfff\ufffe\uffff\x00-\x08\x0b\x0c\x0e-\x1f]', content)
    if invalid:
        line = content.count('\n',0,invalid.start())+1
        raise ValueError(f'文档第{line}行包含不可显示字符 U+{ord(invalid[0]):04X}，已停止导出；原资料识别缺口应标注为[无法辨认]，请重试或核对该位置')
