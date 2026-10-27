"""An isolated real desktop/mobile UI fixture with explicit synthetic phase records."""
import asyncio
from datetime import datetime, timedelta, timezone

from scripts import smoke_workspace_refresh_ui as fixture
from studyforge.db import execute, uid

start = datetime.now(timezone.utc) - timedelta(seconds=20)
for resource in ('original_read', 'audio_extract', 'speech', 'frame_extract', 'video_ocr', 'document_export'):
    execute('INSERT INTO execution_spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (uid(), 0, fixture.tasks[0], fixture.fixture.p['id'], fixture.fixture.c['id'], resource, None,
             'Synthetic UI fixture phase', 0, 'completed', start.isoformat(),
             (start + timedelta(seconds=1)).isoformat(), (start + timedelta(seconds=5)).isoformat(), 4000))

for phase in ('讲解撰写','讲解审查','全文总结'):
    execute('INSERT INTO execution_spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (uid(),0,fixture.tasks[0],fixture.fixture.p['id'],fixture.fixture.c['id'],'model',None,
             '['+phase+'] writer',0,'completed',start.isoformat(),
             (start+timedelta(seconds=1)).isoformat(),(start+timedelta(seconds=5)).isoformat(),4000))

fixture.fixture.case['timing_fixture'] = 'synthetic UI records; not real model/video timings'
if __name__ == '__main__':asyncio.run(fixture.fixture.main())
