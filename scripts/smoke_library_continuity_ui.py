"""Saved-note rendering and delayed navigation in an isolated real UI service."""
import asyncio

from pydantic import BaseModel
from scripts import smoke_library_shelf_ui as shelf
from studyforge import library
from studyforge.db import execute, j, now, uid

fixture = shelf.fixture
second = next(b for b in library.catalogue() if b['id'] != fixture.b['id'])

for node in fixture.nodes:
    library.update_node(node['id'], {'start_page':node['start_page'], 'end_page':node['end_page'], 'confirmed':True})
field, polynomial = fixture.nodes[1:3]
notes = ('# 数域与运算\n\n每个非零元素必须能作除数。\n\n'
         r'例如 $\mathbb{Q}(\sqrt2)=\{a+b\sqrt2\mid a,b\in\mathbb{Q}\}$。' + '\n\n'
         r'$$\varepsilon=\frac{b-a}{2}>0$$' + '\n\n'
         '|条件|意义|\n|---|---|\n|非零除数|避免除以零|\n\n'
         '<script>window.unsafeNoteExecuted=true</script>\n\n'
         + '\n\n'.join(f'## 整理片段 {i}\n\n用于验证长笔记的独立滚动、来源定位与窗口关闭。' for i in range(1,61)))
for index, node in enumerate([field, polynomial]):
    current = library.node(node['id'])
    signature = library.reading_signature(library.book(current['book_id']),current,'deepseek','deepseek-flash','none')
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (uid(),node['id'],signature,'deepseek','deepseek-flash','none','completed',
             notes if index == 0 else '# 多项式的阅读笔记\n\nSECOND_NOTE_ONLY\n\n这是另一个节点。',j([]),now(),now()))

extras=[]
for index in range(16):
    extras.append(library.add_node(fixture.b['id'],f'补充节点 {index+1:02d}'))
other_nodes=[]
for index in range(12):
    other_nodes.append(library.add_node(second['id'],f'另一教材节点 {index+1:02d}'))

fixture.case.update(second_book_id=second['id'],second_nodes=other_nodes,
                    field_node_id=field['id'],polynomial_node_id=polynomial['id'],extra_node_ids=[n['id'] for n in extras])
lag = {'path':'','seconds':0,'remaining':0}

class LagIn(BaseModel):
    path:str
    seconds:float = 1.2
    remaining:int = 1

@fixture.server.app.post('/__library_test__/lag')
def set_lag(value:LagIn):
    if not value.path.startswith('/api/library/'):raise ValueError('fixture library paths only')
    lag.update(value.model_dump())
    return lag

@fixture.server.app.post('/__library_test__/remove-extra')
def remove_extra():
    execute('DELETE FROM library_nodes WHERE id=?',(extras[0]['id'],))
    return {'removed':extras[0]['id']}

@fixture.server.app.middleware('http')
async def delay(request, call_next):
    if request.method == 'GET' and request.url.path == lag['path'] and lag['remaining']>0:
        lag['remaining']-=1
        await asyncio.sleep(lag['seconds'])
    return await call_next(request)

mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)

if __name__ == '__main__':
    asyncio.run(fixture.main())
