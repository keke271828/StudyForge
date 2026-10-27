"""Synthetic long lessons for real desktop + paired HTTPS phone selection."""
import asyncio
import os

from scripts import smoke_lesson_focus_ui as setup

fixture=setup.fixture


def source(marker):
    quote=marker+'😀：为什么取等号仍能排除中点？\r\n这里的原句需要回到开区间解释。'
    section='## 长证明\r\n'+'前面的推导与本次选句无关。\r\n'*550+quote+'\r\n后面仍有其他说明。'
    document='# 这是一份很长的历史讲解\r\n\r\n'+section+'\r\n\r\n## 另一节\r\n不要把选段带入这里。'
    begin=section.index(quote)
    return document,{'start':begin,'end':begin+len(quote),'text':quote}


pc,pc_selection=source('PC_PASSAGE_TAIL')
phone,phone_selection=source('PHONE_PASSAGE_TAIL')
old=setup.seed(fixture.c,'只补长证明后面的原句',pc)
mobile=setup.seed(setup.second,'手机选定具体原句',phone)
fixture.case.update(old_questionnaire=old,phone_questionnaire=mobile,
    pc_selection=pc_selection,phone_selection=phone_selection,process_id=os.getpid())


if __name__=='__main__':asyncio.run(fixture.main())
