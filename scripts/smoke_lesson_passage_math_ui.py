"""Saved proofs crossing a normal page boundary, with controlled tutor calls."""
import asyncio
from scripts import smoke_lesson_passage_ui as base
from scripts import smoke_lesson_focus_ui as setup

formula = r'\(\varepsilon=\frac{b-a}{2}\)'
head = '## 公式与构造\r\n\r\n😀先区分任意正数与方便选择。重复原句。\r\n\r\n'
prefix = head + ('这是定位测试用的历史讲解正文。\r\n' * 300)[:3990-len(head)]
text = (prefix + formula + '\r\n\r\n当 '+r'\(a<b\)'+' 时，两个开邻域可以同时排除中点。\r\n\r\n'
        + r'\[x_n<\frac{a+b}{2},\qquad x_n>\frac{a+b}{2}\]' + '\r\n\r\n'
        + '还可以对照**重复原句。**，这仍是正文。\r\n\r\n```python\nvalue = 2 + 3\n```\r\n\r\n'
        + '<img src="https://invalid.example/lesson-image" onerror="alert(1)">\r\n\r\n'
        + '结束标记：这是历史AI的讲解，不是学生的论证。')
assert 4000 < len(text) < 7000 and text.index(formula) < 4000 < text.index(formula)+len(formula)
pc = setup.seed(base.fixture.c, '公式原句电脑补讲', text)
phone = setup.seed(setup.second, '公式原句手机补讲', text)
base.fixture.case.update(math_questionnaire=pc, math_phone_questionnaire=phone, math_section_text=text,
    math_selection={'start':text.index(formula),'end':text.index(formula)+len(formula),'text':formula})

if __name__ == '__main__':
    asyncio.run(base.fixture.main())
