"""Narrow local evidence boundaries, never a math grader or mind reader."""
import re

_PREFIX=re.compile(r'^(?:(?:最终)?(?:答案|结果|结论)(?:\s*(?:是|为|等于))?|答|(?:我)?选(?:择)?(?:的)?(?:答案|选项)?|选项|(?:answer|result)\b(?:\s+is)?)\s*[:：=]?\s*',re.I)
_NUMBER=r'[-+−]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?'
_VALUE=re.compile(r'(?:'+_NUMBER+r'(?:\s*/\s*'+_NUMBER+r')?(?:\s*(?:%|[A-Za-zµμΩ°][A-Za-z0-9µμΩ°*/^·−-]*))?'
    r'|[-+−]?\\frac\{'+_NUMBER+r'\}\{'+_NUMBER+r'\}|[-+−]?(?:\\sqrt\{\d+\}|\\pi|π|\\infty|∞))')
_VARIABLE=re.compile(r'(?:[A-Za-z](?:_\{?[A-Za-z0-9]+\}?)?|\\(?:alpha|beta|gamma|delta|epsilon|varepsilon|theta|lambda|mu|rho|sigma|phi|omega)|\\(?:mathbf|vec)\{[A-Za-z]\})')
_SHORT=re.compile(r'(?:[A-Ha-h](?:\s*[,，、/]\s*[A-Ha-h])*|[A-H]{2,8}|是|否|对|错|正确|错误|成立|不成立|不一定|真|假|不会|不知道|不懂|不确定|无法作答|yes|no|true|false|I don[’\x27]t know)',re.I)


def result_only(answer):
    """Recognize only obvious short conclusions; unknown prose stays with AI.

    Strip presentation on a temporary copy. Never change the saved answer,
    grade it, or infer a student's cause. Work such as 2+3=4 stays intact.
    """
    if not isinstance(answer,str) or len(answer)>500:return False
    value=answer.strip()
    for _ in range(6):
        before=value
        value=re.sub(r'\*\*([^*]+)\*\*',r'\1',value).strip().rstrip('。.!！;；?？').strip()
        value=_PREFIX.sub('',value,count=1).strip()
        for left,right in (('$$','$$'),('$','$'),('\\(','\\)'),('\\[','\\]'),('`','`')):
            if value.startswith(left) and value.endswith(right) and len(value)>=len(left)+len(right):
                value=value[len(left):-len(right)].strip();break
        if value==before:break
    if not value:return False
    if _SHORT.fullmatch(value) or _VALUE.fullmatch(value):return True
    if value.count('=')==1:
        variable,constant=(part.strip() for part in value.split('=',1))
        return bool(_VARIABLE.fullmatch(variable) and _VALUE.fullmatch(constant))
    return False


def quote(label,text):
    """Every line remains source material, including blank lines and headings."""
    return '\n'.join('> '+line for line in (label+'：'+text).splitlines())
