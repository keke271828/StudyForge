"""Locally verify the constructed examples used to assess teaching outputs.

These are synthetic reference calculations, not a semantic grader for AI prose.
No external code, learner records, model or user exercises are run.
"""
from fractions import Fraction
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    causal = []
    beta, compliance = Fraction(2), Fraction(1, 2)
    for direct in (0, 3, -3):
        # Random assignment Z; half compliers, half never-takers.
        # D(0)=0; D(1)=1 for compliers and 0 otherwise.
        # Y(z,d)=beta*d + direct*z, so controlled D effect remains beta.
        effect = beta*compliance+direct
        causal.append({'direct_assignment_effect': direct, 'controlled_behaviour_effect': int(beta),
                       'assignment_effect_on_behaviour': float(compliance), 'assignment_effect_on_score': float(effect)})
    assert [row['assignment_effect_on_score'] for row in causal] == [1, 4, -2]
    assert causal[1]['assignment_effect_on_score'] > beta and causal[2]['assignment_effect_on_score'] < 0
    # A single t=1 test accepts abstract coefficients outside the Gram constraint.
    # They are NOT claimed to arise from actual vectors.
    A, B, C = 100, 20, 1
    assert A+2*B+C >= 0 and B*B > A*C
    t = -Fraction(B, A)
    assert A*t*t+2*B*t+C == -3
    def square(value): return value*value if value < 100 else 0
    tested = {value: square(value) for value in (-1, 0, 1, 2)}
    assert tested == {-1: 1, 0: 0, 1: 1, 2: 4}
    assert square(100) == 0 and 100**2 == 10000
    # Both obey the supplied lengths. No probability law is specified.
    vectors = {'same_direction': abs(5+12), 'opposite_direction': abs(5-12)}
    assert vectors == {'same_direction': 17, 'opposite_direction': 7}
    # Propositional countermodel: R -> B is true, B is true, R can be false.
    R, B_ = False, True
    assert (not R or B_) and B_ and not R
    folder = ROOT/'build/teaching-inference-20261015'; folder.mkdir(parents=True, exist_ok=True)
    result = {'passed': True, 'scope': 'Constructed-example arithmetic and logic, not model-output accuracy.',
        'causal_model': {'equations': 'D(0)=0; D(1)=1 for half the population, otherwise 0. Y(z,d)=2d+gamma*z.',
            'population_is_synthetic': True, 'random_assignment_is_assumed': True, 'calculations': causal,
            'conclusion': 'Randomized assignment still identifies its effect on uptake; score-effect direction relative to behaviour effect is not fixed without extra assumptions.'},
        'cauchy_coefficient_test': {'A': A, 'B': B, 'C': C, 'f_at_1': A+2*B+C, 'minimum': -3,
            'not_actual_vector_data': True},
        'program_reference': {'provided_test_outputs': tested, 'additional_input_by_local_evaluation_only': 100,
                              'actual': square(100), 'required': 10000},
        'vector_reference': vectors, 'logic_countermodel': {'R': R, 'B': B_}}
    (folder/'合成例子的本机核对.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__': main()
