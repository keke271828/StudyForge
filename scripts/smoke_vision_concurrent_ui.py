"""Real paired desktop/mobile UI showing actual in-flight reuse fixture counts."""
import asyncio
import json
import re

from scripts import smoke_vision_reuse_ui as parent
from studyforge import ai
from studyforge.db import update_job
from studyforge.scheduling import model_slot


fixture=parent.fixture


async def main():
    await ai.source_digest(parent.client,[parent.other])
    calls=[]
    async def request(body,**kwargs):
        from studyforge.vision_batches import admitted_request_body
        async with admitted_request_body(body, 'fixture-native') as body:
            texts=[item['text'] for item in body['messages'][1]['content'] if item['type']=='text']
            calls.append(texts);await asyncio.sleep(.15)
            return json.dumps({'frames':[dict(id=re.search('图片ID：([^；]+)',text)[1],observation='本图独立观察 '+text.split('\n')[-1]) for text in texts]},ensure_ascii=False)
    clients=[ai.DeepSeekClient('fixture-writer',vision_model='fixture-image-model',effort='high') for _ in range(2)]
    for client in clients:client._request_content=request
    stats=[[],[]]
    result=await asyncio.gather(*(ai.source_digest(client,[parent.first],on_cache=stats[i].append) for i,client in enumerate(clients)))
    assert result[0]==result[1] and len(calls)==2
    used=max((row[0] for row in stats),key=lambda value:value['inflight_hits'])
    assert used['inflight_hits']>0 and sum(row[0]['inflight_hits'] for row in stats)==8
    # Parent endpoint includes the native fixture calls in its total counter.
    parent.client.calls+=len(calls)
    update_job(parent.parent.fixture.tasks[0],'paused',35,{'stage':'并发同图核对验收','vision_reuse':used})
    fixture.case.update(expected_timing_cards=10,cache_source_id=parent.first['id'],other_cache_source_id=parent.other['id'],
        vision_reuse=used,concurrent_reuse=True,
        timing_fixture='Synthetic phase durations; real concurrent native-image gateway with simulated responses, PNGs and cache')
    await fixture.main()


if __name__=='__main__':asyncio.run(main())
