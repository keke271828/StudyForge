"""Export the reported legal TeX form via the real PDF exporter; isolated data."""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / 'build' / 'pdf-math-20261011'
os.environ['STUDYFORGE_DATA_DIR'] = str(folder / 'data')

from studyforge.exporters import export_document
import fitz

content = r'''## 原报错写法的等价排版

输入使用不带花括号的根号命令，导出时按 TeX 的单记号规则排版，不改变公式的含义。

$$
\mathbb{Q}(\sqrt2)=\{a+b\sqrt2\mid a,b\in\mathbb{Q}\}
$$

这里的系数 $a,b$ 属于有理数集合 $\mathbb{Q}$。行内根号 $\sqrt2$ 与集合符号应清晰显示，不能导出成原始命令文本。

## 常见简写与带花括号写法

| 简写所表示的对象 | 排版结果 |
| --- | --- |
| 二的平方根 | $\sqrt2$ |
| 二的立方根 | $\sqrt[3]2$ |
| 两个根式的商 | $\frac\sqrt2\sqrt3$ |
| 单记号参数：根号只作用于 2，后面的 3 是另一个因子 | $\sqrt23=3\sqrt2$ |
| 已带花括号的式子保持原意 | $\sqrt{23}$ |

> 引用示例：$\sqrt2$ 是无理数；$\mathbb{Q}$ 表示有理数集合。

## 分行公式

$$
\begin{aligned}
x&=\sqrt2\\
x^2&=2
\end{aligned}
$$

本页仅用于验收公式排版兼容性。真正缺少括号或未知命令的表达式仍会报错，软件不会擅自删去未知符号。
'''

if __name__ == '__main__':
    exported = export_document(content, 'pdf', 'PDF公式兼容性验收', 'PDF公式兼容性验收.pdf')
    deliverable = ROOT / 'output' / 'pdf' / 'PDF公式兼容性验收.pdf'
    deliverable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exported, deliverable)
    with fitz.open(deliverable) as pdf:
        assert len(pdf) == 1
        assert len(pdf[0].get_images()) >= 8
        assert r'\sqrt' not in pdf[0].get_text()
        pdf[0].get_pixmap(matrix=fitz.Matrix(1.8, 1.8)).save(folder / 'page-1.png')
    print(deliverable)
