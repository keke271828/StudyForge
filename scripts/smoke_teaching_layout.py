"""Render sample quotation styles for visual QA without a model call."""
import os
from pathlib import Path

root = Path(__file__).resolve().parent.parent / 'build' / 'teaching-layout'
os.environ['STUDYFORGE_DATA_DIR'] = str(root)

import fitz
from studyforge.exporters import export_document

content = '''# 规训权力：从原文到理解

## 原文主旨

> 福柯的规训权力分析关注日常制度如何塑造行为。
> 规训还可能通过时间安排、持续观察、规范化评判和检查，让人不断调整自己的行为。[社会科学验收.txt｜行 2]

**讲解：**这段话讨论的是制度如何在日常活动中发挥作用。重点是行为被持续观察、比较和调整的过程，需要沿社会科学的概念语境理解。

## 术语释义与批注

**规训权力（disciplinary power）：**这里对应福柯（Michel Foucault）的相关权力分析。理解这个术语，需要同时注意具体制度、评价标准和行为变化，不能只看到“服从”这个表面结果。

> 这些因素可能共同存在，但不能只凭行为相似就认定原因相同。[社会科学验收.txt｜行 4]

**批注：**原文保留了因果解释的边界。同样的行为可能来自外部压力、习惯或主动认同；说明共同结构时，也应说明不同机制。

## 相关延伸

**补充背景：**跨学科或同学科的相关知识需要给出具体对应关系。这一部分用于帮助读懂原文，不替代原作者的论证，也不要求学习者作答。

## 系统性总结

全文依次说明制度安排、观察与比较、行为调整，以及因果判断的边界。引用原文和 AI 解释分别排版，便于对照。术语释义帮助理解关键概念，相关延伸只用于已经说明的联系。
'''

for fmt in ('docx', 'pdf'):
    path = export_document(content, fmt, '讲解排版验收', f'teaching-layout.{fmt}')
    print(path)
    if fmt == 'pdf':
        with fitz.open(path) as document:
            for index, page in enumerate(document):
                page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).save(root / f'page-{index + 1}.png')
