"""Bounded affine-arithmetic hints, never a proof or unconditional error verdict.

Closed parser: no eval, symbolic libraries, model calls or file access. We only
compare adjacent rewrites in equation chains, with the same named variables.
Equalities depending on assumptions still need contextual review.
"""
from fractions import Fraction
import re


class Unsupported(ValueError): pass


def bounded(value):
    if any(number.numerator.bit_length()>512 or number.denominator.bit_length()>512 for number in value.values()):
        raise Unsupported('Arithmetic bounds')
    return {key:number for key,number in value.items() if number}


def add(left,right,sign=1):
    result=dict(left)
    for key,value in right.items():result[key]=result.get(key,Fraction(0))+sign*value
    return bounded(result)


class Parser:
    def __init__(self,text):
        text=re.sub(r'\\(?:left|right)\s*','',text)
        text=re.sub(r'\\(?:,|;|!|:|quad\b|qquad\b|\s)',' ',text).strip()
        if len(text)>1600:raise Unsupported('Expression length')
        pattern=re.compile(r'\s*(\\frac|\d{1,32}(?:\.\d{0,32})?|[A-Za-z]|[+*/(),{}-])')
        self.tokens=[];offset=0
        while offset<len(text):
            match=pattern.match(text,offset)
            if not match:raise Unsupported('Outside the closed grammar')
            self.tokens.append(match[1]);offset=match.end()
        if len(self.tokens)>240:raise Unsupported('Token bounds')
        self.index=0;self.depth=0

    def peek(self):return self.tokens[self.index] if self.index<len(self.tokens) else None

    def take(self):
        token=self.peek()
        if token is None:raise Unsupported('Incomplete expression')
        self.index+=1;return token

    def group(self):
        opener=self.take()
        if opener not in ('(','{'):raise Unsupported('Group required')
        self.depth+=1
        if self.depth>16:raise Unsupported('Depth bounds')
        value=self.sum()
        if self.take()!=(')' if opener=='(' else '}'):raise Unsupported('Unbalanced expression')
        self.depth-=1
        return value

    def atom(self):
        token=self.peek()
        if token in ('+','-'):
            self.take();value=self.atom()
            return value if token=='+' else bounded({key:-number for key,number in value.items()})
        if token in ('(','{'):return self.group()
        if token=='\\frac':
            self.take();numerator=self.group();denominator=self.group()
            return self.divide(numerator,denominator)
        token=self.take()
        if re.fullmatch(r'[A-Za-z]',token):return {token:Fraction(1)}
        try:return bounded({'':Fraction(token)})
        except (ValueError,ZeroDivisionError) as exc:raise Unsupported('Not a rational number') from exc

    @staticmethod
    def multiply(left,right):
        if any(key for key in left) and any(key for key in right):raise Unsupported('Nonlinear product')
        if not any(key for key in left):left,right=right,left
        return bounded({key:value*right.get('',Fraction(0)) for key,value in left.items()})

    @staticmethod
    def divide(left,right):
        if any(key for key in right) or not right.get(''):raise Unsupported('Variable or zero divisor')
        return bounded({key:value/right[''] for key,value in left.items()})

    def product(self):
        value=self.atom()
        while self.peek() is not None:
            token=self.peek()
            if token in ('*','/'):
                self.take();other=self.atom()
                value=self.multiply(value,other) if token=='*' else self.divide(value,other)
            elif token in ('(','{','\\frac') or re.fullmatch(r'[A-Za-z]|\d+(?:\.\d*)?',token):
                value=self.multiply(value,self.atom())
            else:break
        return value

    def sum(self):
        value=self.product()
        while self.peek() in ('+','-'):
            operator=self.take();value=add(value,self.product(),1 if operator=='+' else -1)
        return value

    def parse(self):
        value=self.sum()
        if self.peek() is not None:raise Unsupported('Trailing tokens')
        return value


def expressions(text):
    text=re.sub(r'\\(?:left|right)\s*','',text).strip()
    if text.startswith('(') and text.endswith(')'):
        inner=text[1:-1];depth=0;parts=[];start=0
        for index,char in enumerate(inner):
            if char in '({':depth+=1
            elif char in ')}':depth-=1
            elif char==',' and depth==0:parts.append(inner[start:index]);start=index+1
        if parts:
            parts.append(inner[start:])
            if len(parts)!=2:raise Unsupported('Only two interval endpoints')
            return [Parser(part).parse() for part in parts]
    return [Parser(text).parse()]


def candidates(document,limit=6):
    from .document_render import blocks,inline_parts
    result=[];seen=set()
    try:
        for kind,content in blocks(document):
            formulas=[content] if kind=='math' else [value for item,value in inline_parts(content) if item=='math'] if kind=='paragraph' else []
            for formula in formulas:
                if len(formula)>1600:continue
                parts=formula.strip().rstrip('.,;，。；').split('=')
                if not 2<=len(parts)<=8:continue
                for left,right in zip(parts,parts[1:]):
                    try:
                        a,b=expressions(left),expressions(right)
                        if len(a)!=len(b):continue
                        # A lone scalar equation may be a definition, solution or
                        # assumption, not a simplification. An explicit two-endpoint
                        # rewrite can still be checked without a preceding chain.
                        if len(parts)==2 and len(a)!=2:continue
                        for component,(first,second) in enumerate(zip(a,b),1):
                            names=sorted(key for key in first if key)
                            if names!=sorted(key for key in second if key) or first==second:continue
                            values={name:Fraction(2+3*index) for index,name in enumerate(names)}
                            evaluate=lambda item:sum((number*(values[key] if key else 1) for key,number in item.items()),Fraction(0))
                            before,after=evaluate(first),evaluate(second)
                            if before==after:
                                # Different affine expressions can coincide at
                                # the convenient initial sample. Changing one
                                # variable with a nonzero difference coefficient
                                # by one gives an exact distinguishing witness.
                                # This need not satisfy contextual assumptions:
                                # the existing scope remains a review hint only.
                                key=next((name for name in names if first.get(name,Fraction())!=second.get(name,Fraction())),None)
                                if key is None:continue
                                values[key]+=1
                                before,after=evaluate(first),evaluate(second)
                            signature=(left,right,tuple(values.items()))
                            if signature in seen:continue
                            seen.add(signature)
                            result.append({'formula':formula,'left':left.strip(),'right':right.strip(),
                                'component':component,'components':len(a),
                                'substitution':{key:str(value) for key,value in values.items()},
                                'left_value':str(before),'right_value':str(after),
                                'scope':'局部线性恒等改写存在代入差异；可能依赖额外条件，必须核对上下文，不等于整题或学生答案错误'})
                            if len(result)>=limit:return result
                    except (Unsupported,ValueError,ZeroDivisionError,RecursionError):continue
    except (ValueError,TypeError):pass  # Rendering has its own complete validation.
    return result


def retain_hints(document,reports,language='zh'):
    hints=candidates(document)
    if not hints:return document,reports
    english=language=='en'
    heading='## Local algebra checks to confirm' if english else '## 局部代数核对提示（待核对）'
    note=('These substitutions disagree with an adjacent equality rewrite. Check its stated assumptions; this limited check does not certify a proof or grade an answer.' if english else
          '以下等式改写在本机数值代入时不一致，请核对所写算式和正文的附加条件；这项有限检查不判定整份证明或作答错误，也不能证明其他公式正确。')
    if language=='bilingual':
        heading+=' / Local algebra checks to confirm'
        note+='\n\nThese substitutions disagree with an adjacent equality rewrite. Check its stated assumptions; this limited check does not certify a proof or grade an answer.'
    lines=[heading,note]
    for hint in hints:
        values=', '.join(f'{name}={value}' for name,value in hint['substitution'].items()) or ('numeric calculation' if english else '纯数值计算')
        component=(f"endpoint {hint['component']}" if english else f"第{hint['component']}个端点") if hint['components']>1 else ''
        lines.append(f"- ${hint['left']}$ = ${hint['right']}$：{values}；{component} {hint['left_value']} ≠ {hint['right_value']}。")
    warning='\n\n'.join(lines)
    if warning not in document:
        from .teaching import summary_section
        summary=summary_section(document)
        document=(document[:summary[0]].rstrip()+'\n\n'+warning+'\n\n'+document[summary[0]:]
                  if summary else document.rstrip()+'\n\n'+warning)
    if any(row.get('stage')=='有限本机代数核对' for row in reports):return document,reports
    return document,reports+[{
        'stage':'有限本机代数核对','attempt':1,'passed':None,
        'issues':[{'location':hint['formula'],'problem':hint['scope'],
                   'evidence':f"{hint['substitution']}：{hint['left_value']} ≠ {hint['right_value']}",
                   'candidate':hint} for hint in hints],
        'note':'仅处理有限线性算术等式链；提示仍需核对上下文，无额外模型调用。'}]
