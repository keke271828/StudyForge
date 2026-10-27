"""Isolated desktop + paired phone fixture; real exports, zero cloud calls."""
import asyncio

from scripts import smoke_library_ui as fixture
from studyforge import document_exports as exports
from studyforge.db import create_job, execute, j, now, uid, update_job

content=r'''# 开邻域为什么能够分离

设两个不同的候选极限距离为正。半径取距离的一半时，开区间不包含中点；同一项不能同时位于中点两侧。

$$\mathbb{Q}(\sqrt2)=\{a+b\sqrt2\mid a,b\in\mathbb{Q}\}$$

> 原文：严格小于号排除端点。

[来源：极限.txt｜第 1 段]

## 系统性总结

另存复用的是同一版讲解正文，不需要重新理解原文件或再次调用模型。
'''
source=uid();path=fixture.case_path.parent/'极限.txt';path.write_text('严格小于号排除端点。',encoding='utf-8')
execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
    (source,fixture.p['id'],path.name,'.txt',str(path),'ready',now()))
roots=[]
for failed in (False,True):
    root=create_job(fixture.p['id'],'generate',{'conversation_id':fixture.c['id'],'source_ids':[source]})
    meta={'generation_job_id':root,'conversation_id':fixture.c['id'],'model':'验收讲解模型','review_mode':'express',
          'source_reading':[{'name':'极限.txt','characters':12,'limitations':[]}]}
    exports.save(root,fixture.p['id'],'开邻域与极限唯一',content,[source],meta)
    if failed:
        update_job(root,'failed',100,{'stage':'讲解排版失败'},error='ValueError: 模拟已完成正文的 PDF 排版失败')
    else:
        output=fixture.server.export_document(content,'docx','开邻域与极限唯一',root+'.docx')
        artifact=fixture.server.add_artifact(fixture.p['id'],[source],'explanation','docx','开邻域与极限唯一',output,meta)
        exports.publish_lecture(fixture.server.one('SELECT * FROM document_snapshots WHERE job_id=?',(root,)))
        update_job(root,'completed',100,{'artifacts':[artifact]})
        fixture.case['artifact_id']=artifact['id']
    roots.append(root)
fixture.case.update(saved_job_id=roots[1],lecture_job_id=roots[0])

if __name__=='__main__':asyncio.run(fixture.main())
