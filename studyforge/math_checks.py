"""Bounded exact rational arithmetic and real-vector checks, without eval."""
from __future__ import annotations

import ast
from fractions import Fraction
import math
import re

_NUMBER=re.compile(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?\Z')
_BITS=4096


def _bounded(value):
    if value.numerator.bit_length()>_BITS or value.denominator.bit_length()>_BITS:
        raise ValueError('计算结果过大，请拆成较小的数值核验')
    return value


def rational(expression):
    if not isinstance(expression,str) or not expression.strip() or len(expression)>2000:
        raise ValueError('算式需为1至2000字符的数值表达式')
    expression=expression.strip()
    try:tree=ast.parse(expression,mode='eval')
    except (SyntaxError,ValueError,RecursionError):raise ValueError('数值表达式语法不支持') from None
    if sum(1 for _ in ast.walk(tree))>160:raise ValueError('算式过于复杂，请分步核验')
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):
            literal=ast.get_source_segment(expression,node) or ''
            match=_NUMBER.fullmatch(literal)
            if not match or len(literal)>64 or match[1] and abs(int(match[1]))>100:
                raise ValueError('数字需用十进制，最多64字符，科学计数指数不超过100')
            return _bounded(Fraction(literal))
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value=visit(node.operand);return value if isinstance(node.op,ast.UAdd) else -value
        if isinstance(node,ast.BinOp):
            left,right=visit(node.left),visit(node.right)
            try:
                if isinstance(node.op,ast.Add):value=left+right
                elif isinstance(node.op,ast.Sub):value=left-right
                elif isinstance(node.op,ast.Mult):value=left*right
                elif isinstance(node.op,ast.Div):value=left/right
                elif isinstance(node.op,ast.Pow):
                    if right.denominator!=1 or abs(right.numerator)>32:
                        raise ValueError('幂指数需为-32至32之间的整数')
                    if left==0 and right==0:raise ValueError('0的0次幂需要明确约定，本工具不自行设定')
                    value=left**right.numerator
                else:raise ValueError('仅支持加减乘除、括号和有界整数幂')
            except ZeroDivisionError:raise ValueError('除数不能为零，零也不能取负整数幂') from None
            return _bounded(value)
        raise ValueError('仅支持数值、加减乘除、括号和有界整数幂；不执行代码、函数或文件操作')
    try:return visit(tree.body)
    except RecursionError:raise ValueError('算式嵌套过深，请分步核验') from None


def check(operation,expressions,left,right,variable=None):
    if operation == 'rational_identity':
        if left or right:raise ValueError('有理式核验使用expressions，不使用向量参数')
        from .rational_checks import check as rational_identity
        return rational_identity(expressions,variable)
    if operation in ('polynomial_identity','polynomial_derivative'):
        if left or right:raise ValueError('多项式核验使用expressions及适用时的variable，不使用向量参数')
        from .polynomial_checks import check as polynomial
        return polynomial(operation,expressions,variable)
    if variable is not None:raise ValueError('算术或向量核验不填写variable')
    if operation=='arithmetic':
        if not 1<=len(expressions)<=16 or left or right:raise ValueError('算术核验需提供1至16个expressions，不使用向量参数')
        results=[{'expression':text,'exact':str(rational(text))} for text in expressions]
    elif operation=='vectors':
        if expressions or not 1<=len(left)==len(right)<=32:raise ValueError('向量需同维、各含1至32个分量，不使用expressions')
        a=[rational(text) for text in left];b=[rational(text) for text in right]
        dot=aa=bb=Fraction()
        for x,y in zip(a,b):
            dot=_bounded(dot+_bounded(x*y));aa=_bounded(aa+_bounded(x*x));bb=_bounded(bb+_bounded(y*y))
        gap=_bounded(aa*bb-dot*dot);zero=not aa or not bb
        cosine=None if zero else (-1 if dot<0 else 1)*math.sqrt(float(dot*dot/(aa*bb)))
        angle=None if zero else math.degrees(math.acos(max(-1.0,min(1.0,cosine))))
        limited=None if zero else bool((angle in (0.,180.) and gap!=0) or (angle==90. and dot!=0))
        angle_class=('undefined_zero_vector' if zero else 'zero' if gap==0 and dot>0 else
            'straight' if gap==0 and dot<0 else 'acute' if dot>0 else 'obtuse' if dot<0 else 'right')
        results={'dimension':len(a),'dot_product':str(dot),'left_norm_squared':str(aa),'right_norm_squared':str(bb),
            'gram_determinant':str(gap),'cauchy_holds':gap>=0,'zero_vector_present':bool(zero),
            'linearly_dependent':gap==0,'same_direction':None if zero else gap==0 and dot>0,
            'opposite_direction':None if zero else gap==0 and dot<0,
            'angle_class':angle_class,'angle_domain_degrees':None if zero else [0,180],
            'cosine_approx':cosine,'angle_degrees_approx':angle,'angle_approx_resolution_limited':limited}
        if limited:results['angle_warning']='近似夹角因浮点精度看起来等于0°、90°或180°，精确分类并非该端点；请采用精确方向和angle_class，不用近似角改写结论。'
    else:raise ValueError('未知数学核验类型')
    limits=['只核验传入的数值实例，不证明任意对象的定理或确认题意。',
        '向量分量与有理数运算为精确结果；标为approx的角度和余弦为近似值，方向关系以精确判定为准。']
    if operation=='vectors':limits.append('非零实向量的夹角允许0°与180°；点积为正对应0°≤θ<90°，包括同向的0°，不能笼统说一定为锐角。')
    return {'operation':operation,'verified':True,'scope':'给定数值或实有理向量的核验',
        'meaning':'numeric_case_not_general_proof','results':results,
        'limitations':limits}
