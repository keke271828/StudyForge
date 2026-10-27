"""Bounded rational-coefficient polynomials; no eval, code execution or CAS."""
from __future__ import annotations

import ast
from fractions import Fraction
import re

from .math_checks import _bounded,rational

_NAME=re.compile(r'[A-Za-z][A-Za-z0-9_]{0,15}\Z')
_MAX_TERMS=128
_MAX_DEGREE=24


class Polynomials:
    def __init__(self):self.variables=set();self.work=0

    def tick(self,count=1):
        self.work+=count
        if self.work>20000:raise ValueError('多项式展开超过计算范围，请拆成更小的恒等核对')

    def name(self,value):
        if not isinstance(value,str) or not _NAME.fullmatch(value):raise ValueError('变量需为1至16位ASCII字母开头的字母、数字或下划线名称')
        self.variables.add(value)
        if len(self.variables)>6:raise ValueError('一次多项式核对最多6个独立交换变量')
        return value

    def add(self,left,right,sign=1):
        result=dict(left)
        for monomial,coefficient in right.items():
            self.tick();value=_bounded(result.get(monomial,Fraction())+sign*coefficient)
            if value:result[monomial]=value
            else:result.pop(monomial,None)
            if len(result)>_MAX_TERMS:raise ValueError('多项式展开最多128项，请分步核对')
        return result

    def multiply(self,left,right):
        result={}
        for a,x in left.items():
            for b,y in right.items():
                self.tick();powers=dict(a)
                for name,exponent in b:powers[name]=powers.get(name,0)+exponent
                if sum(powers.values())>_MAX_DEGREE:raise ValueError('多项式总次数最多24')
                monomial=tuple(sorted(powers.items()));value=_bounded(result.get(monomial,Fraction())+_bounded(x*y))
                if value:result[monomial]=value
                else:result.pop(monomial,None)
                if len(result)>_MAX_TERMS:raise ValueError('多项式展开最多128项，请分步核对')
        return result

    def parse(self,expression):
        if not isinstance(expression,str) or not expression.strip() or len(expression)>2000:raise ValueError('每个多项式表达式需为1至2000字符')
        expression=expression.strip()
        try:tree=ast.parse(expression,mode='eval')
        except (SyntaxError,ValueError,RecursionError):raise ValueError('多项式语法不支持；乘法用*，幂用**，不接受LaTeX') from None
        if sum(1 for _ in ast.walk(tree))>160:raise ValueError('多项式语法过于复杂，请分步核对')
        def visit(node):
            self.tick()
            if isinstance(node,ast.Constant) and type(node.value) in (int,float):
                value=rational(ast.get_source_segment(expression,node) or '')
                return {():value} if value else {}
            if isinstance(node,ast.Name):return {((self.name(node.id),1),):Fraction(1)}
            if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
                value=visit(node.operand)
                return value if isinstance(node.op,ast.UAdd) else {key:-number for key,number in value.items()}
            if isinstance(node,ast.BinOp):
                if isinstance(node.op,ast.Pow):
                    if not isinstance(node.right,ast.Constant) or type(node.right.value) is not int or not 1<=node.right.value<=8:
                        raise ValueError('多项式幂指数需直接写1至8的整数；零次幂、负幂和分数幂不在此操作范围')
                    base=visit(node.left);value={():Fraction(1)}
                    for _ in range(node.right.value):value=self.multiply(value,base)
                    return value
                left,right=visit(node.left),visit(node.right)
                if isinstance(node.op,ast.Add):return self.add(left,right)
                if isinstance(node.op,ast.Sub):return self.add(left,right,-1)
                if isinstance(node.op,ast.Mult):return self.multiply(left,right)
                if isinstance(node.op,ast.Div):
                    if any(key for key in right):raise ValueError('多项式只允许除以非零有理常数，不约去含变量的分母')
                    divisor=right.get((),Fraction())
                    if not divisor:raise ValueError('除数不能为零')
                    return {key:_bounded(value/divisor) for key,value in left.items()}
            raise ValueError('仅接受有理系数、交换变量、加减乘、非零常数除法和有界正整数幂；不执行函数、属性、下标或代码')
        try:return visit(tree.body)
        except RecursionError:raise ValueError('多项式嵌套过深，请分步核对') from None

    def derivative(self,polynomial,variable):
        variable=self.name(variable);result={}
        for monomial,coefficient in polynomial.items():
            self.tick();powers=dict(monomial);power=powers.get(variable,0)
            if not power:continue
            if power==1:del powers[variable]
            else:powers[variable]=power-1
            result[tuple(sorted(powers.items()))]=_bounded(coefficient*power)
        return result


def normal_form(polynomial):
    if not polynomial:return '0'
    parts=[]
    for monomial,coefficient in sorted(polynomial.items()):
        factors=[name if power==1 else name+'**'+str(power) for name,power in monomial]
        parts.append('('+str(coefficient)+')'+('*'+'*'.join(factors) if factors else ''))
    return ' + '.join(parts)


def check(operation,expressions,variable):
    algebra=Polynomials()
    if operation=='polynomial_identity':
        if len(expressions)!=2 or variable is not None:raise ValueError('恒等核对需恰好两个expressions，不填写variable')
        left,right=(algebra.parse(text) for text in expressions);difference=algebra.add(left,right,-1)
        results={'left_normal_form':normal_form(left),'right_normal_form':normal_form(right),
                 'difference':normal_form(difference),'identical':not difference}
    elif operation=='polynomial_derivative':
        if len(expressions) not in (1,2) or variable is None:raise ValueError('形式偏导需variable与1个表达式；第二个表达式可填写待核对的导数')
        algebra.name(variable);value=algebra.parse(expressions[0]);derivative=algebra.derivative(value,variable)
        results={'variable':variable,'normal_form':normal_form(value),'derivative':normal_form(derivative)}
        if len(expressions)==2:
            expected=algebra.parse(expressions[1]);difference=algebra.add(derivative,expected,-1)
            results.update(expected_normal_form=normal_form(expected),difference=normal_form(difference),matches=not difference)
    else:raise ValueError('未知多项式核验类型')
    results['variables']=sorted(algebra.variables)
    return {'operation':operation,'verified':True,'meaning':'formal_polynomial_algebra_not_complete_theorem',
        'scope':'有理系数、独立交换变量的多项式代数恒等或形式偏导','results':results,
        'limitations':['verified只表示本机计算完成；恒等是否成立看identical，待核对导数是否一致看matches。',
            '变量独立且可交换；未应用题目中的额外关系，不支持矩阵或非交换对象。',
            '不相同只表示不是无条件恒等式，可能在特定取值或附加条件下相等。',
            '只核对代数与形式偏导，不判定不等式、定义域、量纲、极限、定理条件、题意或学生掌握。',
            '把各变量视为独立；对时间的复合函数求导需另用链式法则，本工具不自动把变量视为时间函数。',
            '不支持函数、变量分母、无理数与LaTeX；幂指数1至8、总次数24、展开128项、最多6个变量。']}
