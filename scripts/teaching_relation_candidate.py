"""Development probe: derive a useful relation before choosing a construction."""
from studyforge.teaching_policy import REASONING_TEACHING_RULES

VERSION='2026-10-16-construction-relations-candidate'
BEFORE=('需要解释构造时，从目标或条件说明为什么值得尝试，再接上可核验的公开推导；'
        '重建思路不冒充真实发现史。')
AFTER=('解释构造时，把目标和当前障碍接起来，推回所选对象需要满足的关系或参数范围，'
       '再给一种合法选择并验证怎样推进目标；重建思路不冒充真实发现史。')
BASELINE_RULES=REASONING_TEACHING_RULES.replace(AFTER,BEFORE,1)
assert BASELINE_RULES.count(BEFORE)==1
RULES=BASELINE_RULES.replace(BEFORE,AFTER,1)

CASES=[
 {'id':'cauchy_parameter','title':'柯西证明：参数是在补哪一个缺口','role':'tutor','style':'balanced','mode':'deep','phase':'development',
  'source':r'实向量a,b。A=Σa_i²，B=Σa_i b_i，C=Σb_i²。f(t)=Σ(ta_i+b_i)²=At²+2Bt+C≥0对所有实数t成立。A>0时顶点t=−B/A给出C−B²/A≥0；A=0时a为零向量且B=0。目标B²≤AC。',
  'question':'我会展开平方和，也会套判别式，但看见题目时想不到为什么要放一个t进去。请从想控制B²这个目标往回讲：t让我们能调什么，它怎样把需要的关系送到面前？用A=1、C=100说明t=±1提供的信息为什么不够，不要把不可能的B伪装成真实向量。只补这个思路，不重抄整份证明，不出题。',
  'checks':['固定±1仅得|B|≤50.5，目标|B|≤10','对A=1 C=100可用t=±10的非负性得到目标；极小值法t=−B/A另一个优化','不能混淆最小f与最优界所选t','解释构造怎样产生所需交叉项及可调约束，保留A=0处理']},
 {'id':'limit_radius','title':'极限唯一性：从矛盾条件反推半径','role':'lecture','style':'balanced','mode':'deep','phase':'development',
  'source':r'若x_n→a且x_n→b，假设a<b。任意ε>0对应两个门槛N1,N2，超过max(N1,N2)同时有|x_n−a|<ε、|x_n−b|<ε。教材取ε=(b−a)/2，使同一项严格小于又严格大于中点。',
  'question':'我想学会自己想到这个ε，而不是记住“取一半”。请先说明我们想让哪两个范围不能兼容，再推回ε应该满足什么，最后选择一个合法值并把证明接完。a=2、b=6可以作为反证假设中的假想极限演示，门槛仍保留符号，别捏造一个真能收敛到两个值的数列。最后总结，不出题。',
  'checks':['开邻域不交要求2ε≤b−a，半距等号可用','全称定义允许选合法正数，a<b保证正性','N=max保持符号，一般不知道数值','更小半径同样可行，不把相交说成一定不存在其他证明']},
 {'id':'integrating_factor','title':'微分方程：积分因子为什么是指数','role':'tutor','style':'balanced','mode':'deep','phase':'development',
  'source':r'区间上p,q连续，y可微，y′+p(x)y=q(x)。乘积法则(μy)′=μy′+μ′y。若μ′=pμ，左边乘μ后可合成乘积导数。取μ=exp(∫p(x)dx)，它处处非零。示例y′+2y=3x。',
  'question':'μ=e的积分次方我能背，但为什么一开始要往乘积导数上想、又怎么从目标找到μ？请从要解决的障碍讲起，推回μ该满足的条件，再在y′+2y=3x上算到通解并代回核对。不要把这种方法说成唯一方法，也不出题。',
  'checks':['由想合成(μy)′匹配系数μ′=pμ','μ=e^(∫p)是合法非零选择，倍乘常数不影响','示例解y=3x/2−3/4+Ce^(−2x)','代回导数与原式核对，不乱除未知y或p']},
 {'id':'binary_boundary','title':'编程：二分边界更新怎样从目标推出','role':'lecture','style':'clear','mode':'deep','phase':'heldout',
  'source':'问题：在非降序数组a中找第一个a[i]≥target的位置，不存在返回len(a)。半开范围[lo,hi)，初始lo=0,hi=len(a)，mid=(lo+hi)//2。若a[mid]<target则lo=mid+1，否则hi=mid。数组可能含重复值。',
  'question':'这两种更新我总背反。请从“第一个不小于target”的目标解释为什么可以丢掉哪些位置、为什么另一边还要保留mid，再说明范围一定缩小。用[1,2,2,4]找2完整走一遍。给静态推演，最后总结，不写新作业，不声称已经运行代码。',
  'checks':['mid小于target则所有≤mid的元素也小，丢弃','mid满足时仍可能是第一个，不丢mid，用hi=mid','空区间时lo是边界或len，不能说真正答案始终在半开区间内','轨迹(0,4)→(0,2)→(0,1)→(1,1)，最终1；每步严格收缩']},
 {'id':'energy_multiplier','title':'力学：乘速度如何连接运动与能量','role':'tutor','style':'balanced','mode':'deep','phase':'heldout',
  'source':r'一维模型m x″=−kx，m,k为正常数，v=x′。乘以v后mvv′=−kxx′，由链式法则得到d/dt(mv²/2+kx²/2)=0。示例m=2,k=8，初始x=1,v=0。',
  'question':'我会跟着算，但想不到为什么乘速度v。我看到kx也可能想乘位置x。请讲清目标导数和两项结构怎样提示乘v，再算出例子的能量及到x=0时速率。v=0的转折点会不会让这一步不合法？不要说乘x永远不能得到任何有用信息，只讲这个方法，不出题。',
  'checks':['利用链式法则vv′与xx′各是平方的导数','乘v不要求v非零，不偷除v','E=4，x0处速率2，速度可能±2','乘x的直接积不是目标导数，不能据此断言所有其他方法无用']},
 {'id':'relative_decay','title':'化学模型：分离变量为何出现对数','role':'lecture','style':'balanced','mode':'deep','phase':'heldout',
  'source':r'给定浓度模型dc/dt=−kc，c(0)=c0>0，k≥0常数，t≥0。这里只讨论c>0的范围。dc/c=−kdt，定积分得ln(c/c0)=−kt，故c=c0 exp(−kt)。c有浓度单位，k单位为时间的倒数。',
  'question':'分离变量这一步是怎么想到的，为什么除以c之后能积分成对数？请从变化率与当前浓度成正比的结构推回操作，解释对数里为什么用c/c0。再用c0=8 mol/L、k=ln2每小时算2小时后的浓度并核对单位，最后总结。不讲整套化学动力学，不出题。',
  'checks':['c>0允许除c，1/c积分产生ln并用比值保持无量纲','c2=2mol/L，kt无量纲，单位正确','k=0为常量c0，不错误要求除k','不能由反应方程式自行推广速率模型']},
 {'id':'nonconstruction_control','title':'哲学对照：没有构造任务时照常解释','role':'lecture','style':'clear','mode':'overview','phase':'heldout',
  'source':'这段文字区分事实判断与评价原则：一个做法很普遍，只说明它经常发生，不能仅凭普遍性推出它值得接受。也不能因此推出它一定不可接受。本文没有提供这一讨论的首创者。',
  'question':'只用这段文字，简明讲清“不能推出值得接受”为什么也不等于“已经证明不可接受”，用一个标为假设的小例子接回意思。不需要数学模型、参数或证明模板。最后总结，不出题。',
  'checks':['不足以支持与反证结论分清','保持原学科与来源边界，不造首创者','已讲完假设例子，不加公式参数或新作业','不因新方法规则强套构造栏目']},
]
