"""Exact rational-expression identities with original denominator restrictions.

No cancellation can remove a restriction. Equality is checked on the common
domain only; roots, inequalities and equality of domains are not inferred.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from fractions import Fraction
import json

from .math_checks import _bounded, rational
from .polynomial_checks import Polynomials, normal_form


@dataclass
class RationalForm:
    numerator: dict
    denominator: dict
    nonzero_conditions: list[dict]


class RationalExpressions(Polynomials):
    def parse(self, expression):
        if not isinstance(expression, str) or not expression.strip() or len(expression) > 2000:
            raise ValueError('每个有理式需为1至2000字符')
        expression = expression.strip()
        try:
            tree = ast.parse(expression, mode='eval')
        except (SyntaxError, ValueError, RecursionError):
            raise ValueError('有理式语法不支持；乘法用*，幂用**，不接受LaTeX') from None
        if sum(1 for _ in ast.walk(tree)) > 160:
            raise ValueError('有理式过于复杂，请分步核对')
        conditions = {}
        one = {(): Fraction(1)}

        def require_nonzero(value):
            if not value:
                raise ValueError('有理式含恒为零的除数，没有可核对的公共定义域')
            if all(not term for term in value):
                return
            # Scalar multiples have the same explicit nonzero restriction.
            coefficient = value[max(value)]
            normalized = {term: _bounded(number / coefficient) for term, number in value.items()}
            key = tuple(sorted(normalized.items()))
            if key not in conditions:
                if len(conditions) >= 32:
                    raise ValueError('每个有理式最多保留32个分母非零条件，请分步核对')
                conditions[key] = normalized

        def visit(node):
            self.tick()
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = rational(ast.get_source_segment(expression, node) or '')
                return ({(): value} if value else {}), one
            if isinstance(node, ast.Name):
                return {((self.name(node.id), 1),): Fraction(1)}, one
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                numerator, denominator = visit(node.operand)
                return (numerator if isinstance(node.op, ast.UAdd) else {k: -v for k, v in numerator.items()}), denominator
            if isinstance(node, ast.BinOp):
                if isinstance(node.op, ast.Pow):
                    power = node.right
                    negative = isinstance(power, ast.UnaryOp) and isinstance(power.op, ast.USub)
                    literal = power.operand if negative else power
                    if not isinstance(literal, ast.Constant) or type(literal.value) is not int or not 1 <= literal.value <= 8:
                        raise ValueError('有理式幂指数需直接写1至8或-1至-8的整数；不支持零次幂')
                    numerator, denominator = visit(node.left)
                    if negative:
                        require_nonzero(numerator)
                        numerator, denominator = denominator, numerator
                    top, bottom = one, one
                    for _ in range(literal.value):
                        top = self.multiply(top, numerator)
                        bottom = self.multiply(bottom, denominator)
                    return top, bottom
                top_a, bottom_a = visit(node.left)
                top_b, bottom_b = visit(node.right)
                if isinstance(node.op, (ast.Add, ast.Sub)):
                    top = self.add(self.multiply(top_a, bottom_b), self.multiply(top_b, bottom_a),
                                   -1 if isinstance(node.op, ast.Sub) else 1)
                    return top, self.multiply(bottom_a, bottom_b)
                if isinstance(node.op, ast.Mult):
                    return self.multiply(top_a, top_b), self.multiply(bottom_a, bottom_b)
                if isinstance(node.op, ast.Div):
                    require_nonzero(top_b)
                    return self.multiply(top_a, bottom_b), self.multiply(bottom_a, top_b)
            raise ValueError('仅支持有理数、独立交换变量、四则、括号和有界非零整数幂；不执行函数、属性、下标或代码')

        try:
            numerator, denominator = visit(tree.body)
        except RecursionError:
            raise ValueError('有理式嵌套过深，请分步核对') from None
        return RationalForm(numerator, denominator, list(conditions.values()))


def check(expressions, variable=None):
    if len(expressions) != 2 or variable is not None:
        raise ValueError('有理式恒等核对需恰好两个expressions，不填写variable')
    algebra = RationalExpressions()
    left, right = (algebra.parse(text) for text in expressions)
    cross = algebra.add(algebra.multiply(left.numerator, right.denominator),
                        algebra.multiply(right.numerator, left.denominator), -1)

    def restrictions(value):
        return sorted(normal_form(condition) for condition in value.nonzero_conditions)

    a, b = restrictions(left), restrictions(right)
    result = {
        'operation': 'rational_identity', 'verified': True,
        'meaning': 'rational_identity_on_common_domain_not_domain_equivalence',
        'scope': '有理系数、独立交换实变量的有理式在公共定义域上的代数恒等核验',
        'results': {
            'identical_on_common_domain': not cross,
            'cross_product_difference': normal_form(cross),
            'left': {'numerator': normal_form(left.numerator), 'denominator': normal_form(left.denominator),
                     'nonzero_conditions': a},
            'right': {'numerator': normal_form(right.numerator), 'denominator': normal_form(right.denominator),
                      'nonzero_conditions': b},
            'common_domain_nonzero_conditions': sorted(set(a + b)),
            'domain_comparison': 'same_explicit_restrictions' if a == b else 'not_compared',
            'variables': sorted(algebra.variables),
        },
        'limitations': [
            'verified只表示计算完成；恒等是否成立看identical_on_common_domain，并且只在两边均有定义时成立。',
            'nonzero_conditions列出的每个多项式都必须不为零；约分、乘零或负幂后仍保留原式限制。',
            '两边限制分别保留；not_compared不表示定义域不同，只表示本工具没有证明它们相同。',
            '不求分母的根，不化简或证明全部定义域条件，不补定义断点，不认证两边是同定义域的同一个函数。',
            '变量独立且可交换，未应用额外关系；不是恒等式仍可能在特定取值或附加条件下相等，不据此给学生判错。',
            '不检查不等式、极限、量纲、真实物理模型或完整定理；不支持函数、LaTeX、无理数与非交换对象。',
            '最多6变量；单式2000字符／160语法节点，幂1至8或-1至-8；中间多项式总次数24、展开128项，总计算量有界。',
        ],
    }
    if len(json.dumps(result, ensure_ascii=False)) > 40000:
        raise ValueError('有理式核验结果过长，请拆成更小的步骤')
    return result
