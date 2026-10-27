"""One conditional follow-up guidance candidate; cases fixed before sampling."""
from studyforge.teaching_policy import REASONING_TEACHING_RULES

VERSION='2026-10-16-current-gap-only-candidate'
FOCUSED_FOLLOWUP_RULE=(
    '学生明确说已懂某部分或只追问一步时，把篇幅用于剩下的卡点；'
    '只回顾接通它所必需的内容，不重复完整证明、平行解法或再总结。'
    '学生要求全面展开时充分展开。'
)
BASELINE_RULES=REASONING_TEACHING_RULES.replace(FOCUSED_FOLLOWUP_RULE,'',1)
RULES=BASELINE_RULES+FOCUSED_FOLLOWUP_RULE

CASES=[
 {'id':'epsilon_instance','title':'数学追问：只解释全称命题取特例','role':'tutor','style':'balanced','mode':'deep','phase':'development',
  'source':'x_n→a的定义是：对任意ε>0，存在N使n>N时|x_n−a|<ε。反证设同时趋于a和b，a<b，取ε=(b−a)/2。',
  'history':[{'role':'assistant','content':'两个半径为(b−a)/2的开邻域不相交，n>max(N₁,N₂)时，同一项不可能同时属于它们，所以矛盾。'}],
  'question':'开区间、最大阈值和矛盾我都懂了。我只不懂“任意ε”怎么允许主动取(b−a)/2，这不是给定义加限制吗？只补这个逻辑，不重新证明唯一性，不出题。',
  'checks':['全称命题可取合法正数特例','a<b保证所取半径正','不混淆应用定义与仅验证一个值来证明收敛','不再完整展开邻域和三角不等式证明']},
 {'id':'copy_slot','title':'编程追问：不重新讲浅复制，只补槽位替换','role':'tutor','style':'clear','mode':'deep','phase':'development',
  'source':'代码未运行：a=[[1],[2]]; b=a.copy(); b[0]=[9]。a和b是不同外层列表，复制时已有内层列表仍共享。下标赋值替换当前外层的一个元素引用。',
  'history':[{'role':'assistant','content':'a与b外层不同，内层原来共享；b[0].append(3)会修改共享内层，使a也看到变化。'}],
  'question':'外层不同、内层共享和append我已经懂了。这次换成b[0]=[9]，为什么a[0]不变？只补这一句操作，给出静态结果，不重画整套引用关系，不出题。',
  'checks':['右边创建新[9]，只替换b外层槽位','没有修改旧[1]或a外层槽位','a=[[1],[2]], b=[[9],[2]]','不称实际运行，不重新展开append和深复制课程']},
 {'id':'feedback_endpoint','title':'反馈模型追问：有界振荡为何不回归','role':'tutor','style':'balanced','mode':'deep','phase':'heldout',
  'source':'演示用离散模型x_{n+1}=(1−g)x_n，g>0，x_0=1。本题“渐近稳定”要求邻近初值的偏差随n→∞趋于0，不能仅凭有界判断。g=2时x_n=(−1)^n。模型不指具体生物机制。',
  'history':[{'role':'assistant','content':'0<g<2时|1−g|<1所以偏差衰减；g=2时依次为1,-1,1,-1；g=3时1,-2,4,-8。'}],
  'question':'这些数我都会算了。只解释g=2：它没有越来越大，为什么还说不能渐近稳定？别把它说成一定发散到无穷，也别重讲其他g值；不出题。',
  'checks':['不趋于0与趋于无穷不同','|x_n|=1，交替有界但不衰减','针对题设渐近稳定，不把所有稳定概念混为一谈','不自建生物或连续时间模型']},
 {'id':'causal_mechanisms','title':'社会科学追问：区分混杂与反向因果','role':'tutor','style':'clear','mode':'research','phase':'heldout',
  'source':'假想观察：常记笔记与高分相关。可能解释甲：自律同时促使记笔记和努力学习；可能解释乙：原本理解快、成绩好的学生更有余力记笔记。两种只是候选解释，均未取得因果验证。',
  'history':[{'role':'assistant','content':'大样本降低抽样随机误差，但不能自动消除系统偏差；需要区分因果效应、混杂和反向因果。'}],
  'question':'大样本不能证明因果我已经懂了。只比较原文甲和乙：为什么一个叫混杂，一个叫反向因果？请各用一句箭头关系接回同一例子，说明两者能否并存；不要另设计研究，不出题。',
  'checks':['甲共同原因→记笔记，共同原因→成绩','乙成绩/原有能力→记笔记，方向与所问记笔记→成绩相反','可以并存但本资料未证实实际存在','研究模式不强制铺开实验方案']},
 {'id':'instant_derivative','title':'物理追问：瞬间导数零与一段守恒','role':'tutor','style':'academic','mode':'deep','phase':'heldout',
  'source':'E(t)在一个时间区间可微，能量守恒在这里指该区间E(t)恒定。仅知E′(0)=0。允许用数学示意E(t)=E₀+αt²，α>0，α的单位为能量/时间²，不代表某个真实装置。',
  'history':[{'role':'assistant','content':'沿轨迹使用链式法则得到dE/dt；不能因为表达式没有显式t，就认为沿轨迹的总导数自动为0。'}],
  'question':'偏导和总导数的区别我懂了。现在只问：算出t=0时dE/dt=0，为什么不能说这段时间能量守恒？请把“某一瞬间”和“整个区间”讲清，用给定示意核对，不再推运动方程，不出题。',
  'checks':['单点导数0不约束全区间','E′=2αt，0处零但其余正时刻非零','全区间导数恒零、可微等条件下才能推出常量','示意不当成真实物理系统，不重讲链式法则']},
 {'id':'full_chemistry','title':'完整讲解对照：明确要求展开时保留内容','role':'lecture','style':'balanced','mode':'deep','phase':'heldout',
  'source':'本材料给定反应A+B→C的速率模型v=k[A][B]，浓度单位mol/L，速率单位mol/(L·s)，k单位L/(mol·s)。反应式不能单独推出这个速率律。设k=0.2 L/(mol·s)，[A]=0.5 mol/L，[B]=0.3 mol/L。',
  'question':'这次请把整段系统讲透，不是只补一句：解释每个量、为何这样推k的单位、完成给定数值例子，并说明反应方程式与给定速率模型的边界，最后系统总结。可以充分展开必要步骤，不出题。',
  'checks':['给定模型不冒充由反应式推出','单位运算完整','v=0.03 mol/(L·s)','全部明确要求保留，末尾总结，不套短追问模式']},
]
