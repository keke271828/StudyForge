"""Contents discovery through desktop and paired phone UI with native test PDFs."""
import asyncio
import time

import fitz
from scripts import smoke_library_ui as fixture
from studyforge import library,library_toc
from studyforge.db import many


def make(name):
    path=fixture.case_path.parent/(name+'.pdf')
    with fitz.open() as document:
        for number in range(1,9):
            page=document.new_page()
            if number in (3,4):
                page.insert_text((50,50),'目录',fontname='china-s')
                values=[('第一章 数域与代数结构',1),('1 数域与封闭运算',1),('2 多项式的基本概念',2)] if number==3 else [
                        ('第二章 行列式与线性结构',3),('1 行列式定义与性质',3),('2 按行展开的构造',4)]
                for index,(title,printed) in enumerate(values):
                    page.insert_text((50,100+30*index),title,fontname='china-s')
                    page.insert_text((430,100+30*index),str(printed))
            else:
                page.insert_text((50,80),'Front matter or body text. No contents entries here.')
            page.insert_text((50,680),name)
        document.save(path)
    return library.import_book(path,name+'.pdf')['book']


books=[make(name) for name in ('桌面自动目录验收','目录疑点核对验收','手机自动目录验收')]
fixture.case.update(auto_toc_book_id=books[0]['id'],review_toc_book_id=books[1]['id'],phone_toc_book_id=books[2]['id'])
original=library_toc.probe_page
probed=[]
def delayed(book,page):
    if book['id']==books[0]['id']:time.sleep(.45)
    probed.append([book['id'],page])
    return original(book,page)
library_toc.probe_page=delayed


@fixture.server.app.get('/__library_test__/toc-stats')
def statistics():
    return {'probed':probed,'readings':len(many('SELECT id FROM library_readings')),'model_calls':len(fixture.calls)}


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)

if __name__=='__main__':asyncio.run(fixture.main())
