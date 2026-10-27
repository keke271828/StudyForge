"""Independent arithmetic checks for observed teaching mistakes, not AI grading.

These finite calculations test specific claims. They cannot certify an entire
answer, establish learner understanding, or replace source-based evaluation.
"""
from fractions import Fraction
import argparse
import json
from pathlib import Path


def checks():
    # E_z = q(z-z0)/|z-z0|^3 with k*q normalized to one.
    def dipole_axis(z):
        return sum(Fraction(q * (z - z0), abs(z - z0) ** 3)
                   for q, z0 in [(1, 1), (-1, -1)])

    north = dipole_axis(2)
    south_outward = -dipole_axis(-2)
    center = dipole_axis(0)
    assert (north, south_outward, center) == (Fraction(8, 9), Fraction(-8, 9), -2)

    # The reviewer's proposed vector does not have squared norm 100.
    a, b = (1, 0), (30, 10)
    A = sum(x*x for x in a)
    B = sum(x*y for x, y in zip(a, b))
    C = sum(y*y for y in b)
    assert (A, B, C) == (1, 30, 1000)
    assert B*B <= A*C

    # Bound-optimization and polynomial-minimization parameters differ.
    f = lambda t: t*t + 100
    bound_parameter, vertex_parameter = 10, 0
    assert f(bound_parameter) == 200 and f(vertex_parameter) == 100

    # A uniform field along z crossing an empty cube is a complete example.
    E0, edge = 3, 2
    face_fluxes = [E0*edge**2, -E0*edge**2, 0, 0, 0, 0]
    assert sum(face_fluxes) == 0 and E0 != 0
    # Two equally weighted types, selected into different groups. Potential
    # outcomes are known only because this is a hypothetical counterexample.
    y0, y1 = [0, 0], [10, 0]
    observed_difference = y1[0] - y0[1]
    ate = sum(a-b for a, b in zip(y1, y0)) / 2
    att = y1[0] - y0[0]
    selection_bias = y0[0] - y0[1]
    assert observed_difference == att + selection_bias
    assert observed_difference != ate + selection_bias
    return {
        'scope': '仅核对本次观察到的具体论断，不证明整份回答正确，也不推断学生能力。',
        'checks': [
            {'claim': '等量异号点电荷都在球内，故没有场线穿过球面',
             'conditions': '+q 位于 z=1，-q 位于 z=-1，球面 R=2；kq=1，排除电荷奇点',
             'outward_normal_field_north': str(north),
             'outward_normal_field_south': str(south_outward),
             'verdict': '错误：局部通量不为零，整体净通量仍为零。'},
            {'claim': '上述偶极子中点电场为零', 'field_z_at_center': str(center),
             'verdict': '错误：中点处两个场同向相加。'},
            {'claim': 'a=(1,0)、b=(30,10) 可以产生 A=1、B=30、C=100',
             'actual_coefficients': {'A': A, 'B': B, 'C': C},
             'verdict': '错误：C=1000；审查者举例算错。原回答的系数反例只测试单一条件是否足够，不声称真实向量违反柯西不等式。'},
            {'claim': '最佳界的 t=sqrt(C/A) 就是 f 的最小值点 t=-B/A',
             'conditions': 'A=1、B=0、C=100',
             'bound_parameter': bound_parameter, 'vertex_parameter': vertex_parameter,
             'f_at_bound_parameter': f(bound_parameter), 'f_at_vertex_parameter': f(vertex_parameter),
             'verdict': '错误：两种优化的对象不同，参数一般不相等。'},
            {'claim': '空区域净通量零，则该区域电场处处零',
             'conditions': '理想静态均匀场 E=3*z_hat；立方体边长2',
             'face_fluxes': face_fluxes, 'net_flux': sum(face_fluxes), 'field_magnitude': E0,
             'verdict': '错误：非零场可有零净通量；该静态场可取电势 phi=-3z，满足 curl(E)=0。'},
            {'claim': '观察组间均值差普遍等于总体平均因果效应ATE加基线选择偏差',
             'conditions': '纯假想反例：两类人权重相同，Y0均为0，Y1分别10和0；前一类在处理组，后一类在对照组。不是调查数据，也不表示现实能同时观察两种个体反事实。',
             'observed_difference': observed_difference, 'ATE': ate, 'ATT': att,
             'baseline_selection_bias': selection_bias,
             'verdict': '错误：观察差10、ATE为5、基线偏差0。一般分解用处理组平均效应ATT；换成ATE需额外条件。'}
        ]
    }


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(checks(), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checked_claims': 6, 'model_calls': 0, 'output': str(target)}, ensure_ascii=False))
