"""Actual desktop/mobile cache diagnostics with real images and fixture observations."""
import asyncio
from PIL import Image

from scripts import smoke_task_timing_ui as parent
from studyforge import ai
from studyforge.config import files_dir
from studyforge.db import execute,j,now,uid,update_job

fixture=parent.fixture.fixture


class Vision:
    model='fixture-writer';vision_model='fixture-image-model';effort='high'
    def __init__(self):self.calls=0
    async def analyze_images(self,frames):
        self.calls+=1;return {item['id']:'测试核对：'+item['ocr'] for item in frames}
    async def analyze_image(self,path,locator,text):
        self.calls+=1;return '测试核对：'+text


client=Vision()


def source(name,count):
    ident=uid();parts=[]
    for index in range(count):
        path=files_dir()/(ident+f'-{index}.png');Image.new('RGB',(128,128),(index,40,80)).save(path)
        parts.append(dict(kind='video_frame',locator=f'{index} 秒',text='原始测试OCR '+str(index),meta={'image_path':str(path)}))
    value=dict(id=ident,project_id=fixture.p['id'],name=name,original_path=parts[0]['meta']['image_path'],segments=parts)
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (ident,fixture.p['id'],name,'.png',value['original_path'],j(parts),'ready',now()))
    return value


first=source('重复图片核对验收',8);other=source('保留缓存的其他资料',4)


@fixture.server.app.get('/__vision_reuse__/other')
async def verify_other():
    stats=[];before=client.calls
    digest,_=await ai.source_digest(client,[other],on_cache=stats.append)
    return dict(new_fixture_model_calls=client.calls-before,reuse=stats[0],characters=len(digest))


@fixture.server.app.get('/__vision_reuse__/calls')
def calls():return dict(fixture_model_calls=client.calls,external_model_requests=0)


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)


async def main():
    stats=[]
    await ai.source_digest(client,[first])
    await ai.source_digest(client,[other])
    ai._VISION_CACHE.clear()
    await ai.source_digest(client,[first],on_cache=stats.append)
    assert stats[0]['disk_hits']==8 and stats[0]['new_images']==0 and client.calls==3
    update_job(parent.fixture.tasks[0],'paused',35,{'stage':'图像核对复用验收','vision_reuse':stats[0]})
    fixture.case.update(expected_timing_cards=10,cache_source_id=first['id'],other_cache_source_id=other['id'],
        vision_reuse=stats[0],timing_fixture='Synthetic phase durations; real cache reuse of fixture image observations')
    await fixture.main()


if __name__=='__main__':asyncio.run(main())
