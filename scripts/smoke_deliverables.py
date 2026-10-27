"""Export isolated, self-authored samples for native Office and PDF inspection."""
import argparse
import json
import os
import uuid
from pathlib import Path


CONTENT = r'''# 给定函数模型的学习样例

> 原文：给定 A≥0，ω>0，x(t)=A cos(ωt)。这里只讨论这个函数模型。[样例.txt｜行 1-1]

## 对象、符号与条件

A是幅度，ω是频率参数；这里先研究给定函数，不能据此声称所有实际系统都服从它。
若t以秒为单位，ω以每秒为单位，A与x具有相同的单位。

行内排版：$x(0)=A$，以及$@frac{dx}{dt}=-A@omega@sin(@omega t)$。

## 为什么这样计算

对复合函数使用链式法则，内层ωt的导数是ω；这个因子不能遗漏。

$$

\begin{aligned}
x(t)&=A\cos(\omega t)\\
\dot x(t)&=-A\omega\sin(\omega t)
\end{aligned}
$$

> $$
> x(0)=A
> $$

## 条件表

| 对象 | 说明 |
| --- | --- |
| 幅度A | 给定非负参数，不代表已经测量 |
| 频率ω | 给定正参数；不能省略对应时间单位 |

## 系统性总结

保留对象、参数与适用条件，说明链式法则中频率因子的来由。函数计算正确并不证明现实系统适用。
'''.replace('@',chr(92))

PROGRAMS = {
 'py':('python','# 参数A=1，omega=2，t=0；单位分别为m、s^-1、s；仅给定函数模型。\nimport math\nA,omega,t=1.0,2.0,0.0\nx=A*math.cos(omega*t)\nassert abs(x-1.0)<1e-12\nprint(x)'),
 'js':('javascript','// A=1 m，omega=2 s^-1，t=0 s；仅给定函数模型。\nconst A=1, omega=2, t=0;\nconst x=A*Math.cos(omega*t);\nconsole.log(x);'),
 'ts':('typescript','// A=1 m，omega=2 s^-1，t=0 s；仅给定函数模型。\nconst A:number=1, omega:number=2, t:number=0;\nconsole.log(A*Math.cos(omega*t));'),
 'cpp':('c++','// A=1 m，omega=2 s^-1，t=0 s；仅给定函数模型。\n#include <cmath>\n#include <iostream>\nint main(){double A=1,w=2,t=0;std::cout<<A*std::cos(w*t);return 0;}'),
 'm':('matlab','% 参数A=1 m，omega=2 s^-1，t=0 s；仅给定函数模型，不需要工具箱。\nA=1; omega=2; t=0;\nx=A*cos(omega*t);\nassert(abs(x-1)<1e-12);\ndisp(x);'),
 'wl':('wolfram','(* 参数A=1 m，omega=2 s^-1，t=0 s；仅给定函数模型。 *)\na=1; omega=2; t=0;\nx=a Cos[omega t];\nIf[x!=1,Exit[1]];\nPrint[x];'),
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(Path('build')/('deliverables-'+uuid.uuid4().hex)))
    args=parser.parse_args();root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(root/'data')
    from studyforge.exporters import export_document
    from studyforge.deliverables import inspection
    from docx import Document
    from pptx import Presentation
    import fitz
    paths={};reports={}
    for fmt in ['docx','pdf','pptx','mm','apkg','py','js','ts','cpp','ipynb','m','wl','zip']:
        content=CONTENT
        if fmt=='apkg':
            content=json.dumps({'cards':[
                {'question':'给定函数模型中ω需要满足什么条件？','answer':'ω>0；还需明确时间单位。','source':'[样例.txt｜行 1-1]'},
                {'question':'对x(t)=A cos(ωt)求导时，为什么出现ω因子？','answer':'链式法则：内层ωt的导数为ω。','source':'样例讲解的推导'},
                {'question':'计算给定函数的导数正确，是否证明现实系统服从该模型？','answer':'不能；实际适用需要另外的假设和证据。','source':'[样例.txt｜行 1-1]'}]},ensure_ascii=False)
        elif fmt=='zip':
            content=json.dumps({'files':[{'path':'src/model.py','content':PROGRAMS['py'][1]},
                              {'path':'README.md','content':'# 给定函数模型\nA单位m，omega单位s^-1，t单位s。\n运行：python src/model.py\n仅用标准库；未经运行，不据此证明任何实际系统适用。'},
                              {'path':'requirements.txt','content':'# 无额外依赖'}]},ensure_ascii=False)
        elif fmt in PROGRAMS or fmt=='ipynb':
            label,code=PROGRAMS['py' if fmt=='ipynb' else fmt]
            content=CONTENT+'\n\n## 可运行模型或示例\n```'+label+'\n'+code+'\n```\n'
        path=export_document(content,fmt,'函数模型与条件 · 格式验收','函数模型与条件.'+fmt)
        paths[fmt]=str(path);reports[fmt]=inspection(path)
    Document(paths['docx']);Presentation(paths['pptx'])
    renders=root/'rendered';renders.mkdir(exist_ok=True)
    with fitz.open(paths['pdf']) as pdf:
        for index,page in enumerate(pdf): page.get_pixmap(matrix=fitz.Matrix(1.6,1.6)).save(str(renders/f'pdf-{index+1}.png'))
    report={'isolated':True,'simulated_model':True,'model_calls':0,'paths':paths,'checks':reports,
            'native_office':None,'actual_model_quality_verified':False}
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'root':str(root),'report':str(root/'report.json'),'formats':len(paths)},ensure_ascii=False))


if __name__=='__main__':main()
