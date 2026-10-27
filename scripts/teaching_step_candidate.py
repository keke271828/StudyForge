"""Held-out corrections: preserve legal reasoning while locating a faulty step.

No subject-specific answer is added to the production prompt. Cases are fixed
before collecting answers; last four are held out from policy editing.
"""
from studyforge.teaching_policy import REASONING_TEACHING_RULES

VERSION='2026-10-16-preserve-valid-steps-candidate'
BEFORE='先把结论和用来解释它的理由核对正确，再追求直观。'
AFTER=('先核对结论与理由，再讲直观。学生的推理部分正确时保留有效步骤，'
       '定位哪一步不成立或缺少条件，在原情境中接上正确推导；不为纠错而否定合法操作。')
BASELINE_RULES=REASONING_TEACHING_RULES.replace(AFTER,BEFORE,1)
assert BASELINE_RULES.count(BEFORE)==1
RULES=BASELINE_RULES.replace(BEFORE,AFTER,1)

CASES=[
 {'id':'gauss_factor','title':'物理：常数能提出，但有向面积不能换总面积','role':'tutor','style':'balanced','mode':'deep','phase':'development',
  'source':r'高斯定律为∮_S E·dS=Q内/ε0。设一个空立方体中电场处处为E0 e_x，每个面的面积为A，E0为常数且非零。dS方向取外法向。',
  'history':[{'role':'assistant','content':'六个面通量相加为零，并不意味着电场为零。'}],
  'question':'我已经懂穿入穿出会抵消。但E0是常数，总可以提出积分吧？那我写成E0×6A=0，再除以6A得到E0=0，究竟错在哪一步？请保留我做对的步骤，接着写完这一次计算，别重讲整章，不出题。',
  'checks':['承认E0能提出积分，定位剩余有向面积不能换6A','写出E0(A−A+0+0+0+0)=0','0=0对E0不增加约束，不得除以零','有向面积与总面积含义准确']},
 {'id':'divide_zero','title':'数学：除法有效分支与遗漏的零解','role':'lecture','style':'clear','mode':'deep','phase':'development',
  'source':r'在实数范围解x²=x。一位学生写：两边同时除以x，得到x=1，所以只有一个解。',
  'question':'给我讲清这份解答哪部分能保留、哪部分不成立。我听过“不能除以0”，但不懂怎样接着改这份解答，难道必须放弃除法重做吗？请用这道题走完，解释条件的作用，最后总结，不出题。',
  'checks':['保留x非零时除以x合法，x=1有效','零情形另验满足原式','完整解集{0,1}，不说对变量一律不能除','说明直接因式分解是另一办法而非唯一许可办法']},
 {'id':'gas_temperature','title':'化学：状态方程有效，跨状态不变量需条件','role':'tutor','style':'balanced','mode':'deep','phase':'development',
  'source':r'本题采用理想气体模型pV=nRT，R为常数。同一密闭样品n不变；初态V1=1 L,T1=300 K,p1=100 kPa。末态V2=2 L,T2=600 K。忽略相变。',
  'question':'我先用p=nRT/V，这一步应当没错。体积翻倍就该压强减半，所以我算p2=50 kPa。为什么答案说100 kPa？请从我这一步接着讲，具体代入两态的量，不泛讲整套气体定律，也不出题。',
  'checks':['p=nRT/V合法，p∝1/V的比较遗漏T变化','比值p2/p1=(T2/T1)(V1/V2)=1','给出100kPa、单位和绝对温度条件','不暗称密闭就等温，不把理想关系当普适实气体定律']},
 {'id':'feedback_gain','title':'生物模型：方向为负仍可能振荡发散','role':'lecture','style':'balanced','mode':'deep','phase':'development',
  'source':r'这是演示用离散反馈模型，不指具体生物机制。偏差x_k在每一步受修正−g x_k，故x_{k+1}=(1−g)x_k，g>0为无量纲响应强度。给定x_0=1。',
  'question':'修正量和当前偏差方向相反，所以g越大应该回归得越快，并且总能稳定。我哪一步想多了？保留方向的判断，用g=0.5和g=3各算几步接回“稳定”，别凭空加生物事实，最后总结，不出题。',
  'checks':['反向修正判断正确，不等于每步修正后偏差更小','g0.5序列1,.5,.25,.125；g3序列1,-2,4,-8','渐近稳定0<g<2，g2等幅交替而非衰减','不将演示模型冒充具体生物机制']},
 {'id':'description_norm','title':'哲学：事实依据有用，但规范结论少评价前提','role':'lecture','style':'clear','mode':'deep','phase':'heldout',
  'source':'一份假想调查发现，某社区多数人赞同做法M；这里暂把调查可靠性视为已给条件。有人写：“多数人赞同M，所以应该实行M。”材料没有给出“多数偏好应当优先”等评价原则。',
  'question':'我是不是完全不能用这个调查支持任何决策？请指出原推理缺在哪一步，再说明不丢掉调查结果能怎样补成一个有条件的决策论证。请区分举例补的原则与原文已有内容，最后总结，不出题。',
  'checks':['保留可靠调查作为偏好事实，不能直接推出应该','明确补充评价前提及适用范围，标明假设','不把缺少前提说成M必不可接受','不将多数意见直接当正当性或唯一原则']},
 {'id':'alias_slots','title':'编程：替换外层槽位与修改共享对象','role':'tutor','style':'balanced','mode':'deep','phase':'heldout',
  'source':'代码未运行：\n```python\na = [[0]] * 2\na[0] = [7]\na[1].append(8)\n```\nPython列表相乘复制已有元素引用，列表下标赋值替换一个槽位。',
  'question':'我知道乘2时两个位置原先共享同一个内层列表，所以我认为最后a会是[[7,8],[7,8]]。共享这个判断难道也错了吗？请跟着这两次操作解释对象关系，给出静态结果，不讲整套内存管理、不出题。',
  'checks':['初始共享判断成立，下标赋值使一个槽位指向新对象','最后a=[[7],[0,8]]','append改的是旧[0]，没有改新[7]','不声称代码已执行']},
 {'id':'valid_division','title':'正确推理对照：已知正性时除法合法','role':'tutor','style':'academic','mode':'overview','phase':'heldout',
  'source':r'a,b为实数，b>0，ab≥1。学生推导a≥1/b>0；于是a+b≥2√(ab)≥2。',
  'question':'我这一整段推导有错吗？尤其是除以b和后来用均值不等式。请核对并说明依据；如果没有错，直接确认，不要为了纠错强行找错误，不出题。',
  'checks':['除以正b不变号，a>0由条件推出','AMGM条件已满足，推导正确','不认为缺列a>0故不可用AMGM','不编造错误或无关反例']},
 {'id':'valid_observation','title':'正确推理对照：保留关联，限制因果','role':'lecture','style':'academic','mode':'research','phase':'heldout',
  'source':'假想观察研究报告了A与B的样本关联，但没有排除共同原因。学生总结：“目前可以说这个样本中A与B有关联；不能仅据此认定A导致B，也不能认定A一定不影响B。”',
  'question':'请核对我这段总结，解释它为什么成立或哪里不成立。只评估这段话，不设计一整套研究、不强行找错误，最后总结，不出题。',
  'checks':['样本关联与因果未确定区分正确','未排除共同原因不是已证明完全由混杂造成','不能据此断言无因果效应','不因研究模式强行铺开实验设计']},
]
