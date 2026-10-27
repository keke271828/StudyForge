"""Offline real reading jobs, frozen focus, note variants and paired mobile."""
import asyncio
import json

import fitz
import httpx
from scripts import smoke_library_ui as fixture
from studyforge import library
from studyforge.db import execute, j, now, uid
from studyforge.library_semantic import set_enabled

set_enabled(False)
field, polynomial = fixture.nodes[1:3]
for node in (field, polynomial):
    library.update_node(node['id'], {'start_page': node['start_page'], 'end_page': node['start_page'], 'end_y': .5, 'confirmed': True})
n = library.node(field['id'])
ident = uid()
execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (ident, n['id'], library.reading_signature(fixture.b,n,'deepseek','deepseek-flash',None), 'deepseek', 'deepseek-flash', None, 'completed',
         '# 已有结构索引\n\nOLD_INDEX_AVAILABLE：四则运算封闭，除数不能为零。',now(),now()))
p = library.extract_page(fixture.b,n,n['start_page'])
execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',
        (ident,p['page'],p['locator'],p['original_text'],'',p['image_path'],p['image_sha256']))

path = fixture.case_path.parent/'second-book.pdf'
with fitz.open() as pdf:
    page=pdf.new_page();page.insert_text((50,70),'A separate book. Do not share the reading question draft.')
    pdf.set_toc([[1,'Separate book',1]]);pdf.save(path)
second = library.import_book(path,'另一教材.pdf')['book']
fixture.case.update(field_node_id=n['id'],second_book_id=second['id'],index_reading_id=ident)

original=fixture.respond
async def respond(request):
    if request.method!='POST':return await original(request)
    payload=json.loads(request.content)
    system=payload['messages'][0]['content']
    if not isinstance(system,str) or '这是重点精读' not in system:return await original(request)
    fixture.calls.append(payload)
    await asyncio.sleep(1.8)
    user=payload['messages'][-1]['content']
    question=user.split('用户指定的精读问题（不是原文证据）：\n')[-1].split('\n\n')[0]
    answer=('# 重点精读\n\nDEEP_ORIGINAL_AVAILABLE\n\n精读问题：'+question+'\n\n'
            '## 条件解决了什么困难\n\n非零除数让除法有定义，封闭性让结果仍留在集合内。\n\n'
            r'$$\frac{a+b\sqrt2}{c+d\sqrt2}=\frac{(a+b\sqrt2)(c-d\sqrt2)}{c^2-2d^2}$$'+'\n\n'
            + '\n\n'.join(f'## 原页解释 {i}\n\n来源和条件应当与推导一起理解；这是用于检验界面的固定响应。' for i in range(1,18)))
    return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':answer},'finish_reason':'stop'}]})

fixture.respond=respond
if __name__=='__main__':asyncio.run(fixture.main())
