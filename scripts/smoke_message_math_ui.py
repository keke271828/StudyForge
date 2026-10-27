"""Saved formula reply, with all network model responses controlled."""
import asyncio
from scripts import smoke_message_focus_ui as base
from studyforge.db import execute,now,uid

formula=r'\(A_{ij}=(-1)^{i+j}M_{ij}\)'
text=('## 定理内容\n\n设 '+r'\(D=|A|\)'+' 是 '+r'\(n\)'+' 阶行列式。\n\n'
    '- 余子式：删去第 '+r'\(i\)'+' 行、第 '+r'\(j\)'+' 列得到的行列式。\n'
    '- 代数余子式：'+formula+'。\n\n'
    +r'$$D=\sum_{j=1}^{n}a_{ij}A_{ij}$$'+'\n\n'
    '> 要区分定义与证明，原来的 AI 回答仍需核对。\n\n'
    '重复原句。**重复原句。**\n\n'+('这一段是用于分页显示测试的普通说明。'*240)+
    '\n\n'+r'\[\mathbb{Q}(\sqrt{2})=\{a+b\sqrt{2}\mid a,b\in\mathbb{Q}\}\]'+'\n\n'
    '```python\nformula = r"\\(x^2\\)"\n```\n\n结束标记：完整保存的回答。')
ident=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(ident,base.fixture.c['id'],'assistant',text,now()))
base.fixture.case.update(math_message_id=ident,math_text=text,math_quote=formula)
if __name__=='__main__':asyncio.run(base.fixture.main())
