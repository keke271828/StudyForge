"""Frozen delivered lessons plus distinct correct/incorrect holdout controls."""
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def delivered(suffix,ident,targets):
    import fitz
    folder=ROOT/f'build/lecture-workflow-profile-20261015-{suffix}'
    with sqlite3.connect((folder/'data/studyforge.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        document=db.execute('SELECT content FROM document_snapshots').fetchone()[0]
    path=folder/'十页合成数学原资料.pdf'
    with fitz.open(path) as doc:
        source='\n'.join(f'[来源 {path.name}｜第 {i+1} 页]\n'+page.get_text() for i,page in enumerate(doc))
    return {'id':ident,'source':source,'document':document,'expected_pass':False,'targets':targets,
        'requirements':'只围绕原文讲清极限唯一性的证明，解释方法动机、具体例子和边界；不布置习题。'}


def cases():
    values=[delivered('2','delivered_default',['closed_bounds']),
        delivered('4','delivered_high',['max_not_unique','equal_radius_not_enough','unequal_can_use_midpoint'])]
    values.append({'id':'correct_math_control','expected_pass':True,'targets':[],
        'source':'实数数列收敛到a：每个ε>0都有N，n>N时|x_n-a|<ε。若a<b，两个开邻域半径和不超过b-a则不相交。闭邻域需要半径和严格小于b-a。N可取max(N_1,N_2)，更大的正整数也可。',
        'document':r'''# 半径与门槛的合法选择

假设同一实数数列有不同极限 $a<b$。取 $0<\varepsilon\le(b-a)/2$，两个开邻域没有公共点。取一半距离方便把两条估计写到同一中点；取更小半径同样可行。

## 改变条件后重新核对

若讨论闭区间，半径各取 $d/3$（$d=b-a>0$），端点估计应写成

$$x_n\le a+d/3<b-d/3\le x_n.$$

中间严格不等式来自 $2d/3<d$，所以整条链矛盾。不能把两侧估计写成严格小于或大于。

半径不等也不意味着中点一定不能分隔两区间。例如 $a=0,b=4,r_1=1/2,r_2=1$，两个开区间是 $(-1/2,1/2)$ 与 $(3,5)$；中点2仍在间隙内。一般应看实际端点，不能由“不等”直接排除一个分隔点。

## 统一尾部

取 $N=\max(N_1,N_2)$，$n>N$ 时两条尾部约束同时成立。必须让所用下标同时越过两门槛，但N本身不必恰好等于最大值；取两者之和也可，只是不如最大值紧凑。

## 系统性总结

取半径由不相交条件决定，统一下标由两尾部的交集决定。充分构造不必是唯一选择，开闭端点需要分别核对。''',
        'requirements':'仅解释给出的构造、边界及替代选择，不出题。'})
    source='调查发现记笔记频率与成绩相关，不能单靠大样本证明因果。随机干预若估计出正平均效应，也不保证每个个体受益；统计显著不等于效应很大。假设示例须标明并不当成调查事实。'
    values.append({'id':'flawed_causal_holdout','expected_pass':False,'targets':['average_not_everyone','significance_not_large'],
        'source':source,'document':'''# 从笔记调查到教学建议

调查样本很大且成绩差异显著，因此我们已知道记笔记对成绩的作用很大，不必再看效应量。

即使现在不把关联当因果，未来随机实验只要发现正的平均因果效应，就能断言每个学生都能从多记笔记中获益。平均效应为正已经保证所有个体的作用方向相同。

## 系统性总结

样本和显著性告诉我们作用很大，正平均效应保证每个人受益。''',
        'requirements':'解释统计证据能支持什么，区分关联、因果、效应大小与个体差异。'})
    values.append({'id':'correct_social_control','expected_pass':True,'targets':[],
        'source':source,'document':'''# 调查与因果边界

大样本可以降低估计中的随机误差，仍不能仅凭统计显著就认定因果或效应很大。需要看设计、效应量和可能的系统偏差；问卷里没有测量的机制，只能当待检验解释。

举一个纯假设的示意：两组成绩差异可能受到先前学习习惯影响。这不是本次调查已经发现的事实，也没有据此断言先前习惯一定提高成绩。这里的例子只是说明为什么两组可能不可直接比较。

即使随机实验得到正的平均因果效应，也不能推出每个个体必定受益。平均值可以由正负不同的个体效应组成；针对具体学生仍需另看适用条件。

## 系统性总结

依次区分关联是否稳定、能否识别因果、平均效应多大，以及个体差异；条件不足只限制对应断言，不否定已经支持的关联。''',
        'requirements':'只讲证据边界，允许明确标明的假设例子，不把可选背景当实质遗漏，不出题。'})
    return values
