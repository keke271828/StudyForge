"""Finite counterexamples to claims actually observed in teaching samples.

Exact arithmetic checks these particular statements, not an entire lesson or
the student's understanding. No model, private learner data or external source.
"""
from fractions import Fraction as F
import json
from pathlib import Path


def mean(values): return sum(values, F(0)) / len(values)


def check():
    # C and U are independent equiprobable +/-1. Both disturbances are U:
    # each is independent of C; they are not independent of each other.
    worlds = [(c, u) for c in (-1, 1) for u in (-1, 1)]
    c = [F(a) for a, _ in worlds];u = [F(b) for _, b in worlds]
    x = [a + b for a, b in zip(c, u)];y = list(x)
    variance_c = mean([a*a for a in c]) - mean(c)**2
    covariance_xy = mean([a*b for a, b in zip(x,y)]) - mean(x)*mean(y)
    covariance_disturbances = mean([a*a for a in u]) - mean(u)**2
    assert covariance_xy == variance_c + covariance_disturbances == 2
    assert covariance_xy != variance_c
    # Positivity also requires a nondegenerate common cause; positive
    # coefficients alone do not give strictly positive variance/covariance.
    constant = [F(0)]*4
    assert mean([a*a for a in constant])-mean(constant)**2 == 0

    # Random promotion A is independent of U; actual consumption D=A*U is not.
    # Y=U has no causal dependence on D. Four worlds have equal probability.
    treatment_worlds = [(a,u,a*u,u) for a in (0,1) for u in (0,1)]
    intent_to_treat = mean([F(y) for a,_,_,y in treatment_worlds if a==1]) - mean([F(y) for a,_,_,y in treatment_worlds if a==0])
    consumption_difference = mean([F(y) for _,_,d,y in treatment_worlds if d==1]) - mean([F(y) for _,_,d,y in treatment_worlds if d==0])
    assert intent_to_treat == 0 and consumption_difference == F(2,3)

    a,b = F(1),F(5)
    radii = [(b-a)/2,(b-a)/3]
    assert all(a+r<=b-r for r in radii)
    large_radius, common_point = F(3),F(3)
    assert abs(common_point-a)<large_radius and abs(common_point-b)<large_radius
    a,b = F(2),F(5);epsilon=(b-a)/2
    correct_right_endpoint = b+epsilon
    observed_wrong_endpoint = (a+3*b)/2
    assert correct_right_endpoint == F(13,2) and observed_wrong_endpoint == F(17,2)
    assert correct_right_endpoint != observed_wrong_endpoint
    return {
        'scope':'Exact finite counterexamples; not whole-answer certification',
        'independent_of_common_cause_does_not_mean_mutually_uncorrelated':{
            'declared_formula_value':str(variance_c),'actual_covariance':str(covariance_xy),
            'missing_disturbance_covariance':str(covariance_disturbances)},
        'random_assignment_does_not_randomize_actual_consumption':{
            'assignment_effect':str(intent_to_treat),'consumption_group_difference':str(consumption_difference),
            'actual_consumption_causal_effect':'0 in this constructed model'},
        'limit_neighborhoods':{'half_and_third_are_disjoint':True,'larger_positive_radius_can_overlap':True,
                               'right_endpoint_actual':str(correct_right_endpoint),'observed_wrong_endpoint':str(observed_wrong_endpoint)},
    }


if __name__=='__main__':
    target = Path('build/learning-quality-20261013-final/claim-checks.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    results = check()
    target.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False))
