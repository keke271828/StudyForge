"""Reproduce the old candidate gate and bound the one-time legacy migration."""
import ast
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]


def main(name):
    folder=(ROOT/'build'/name).resolve()
    if folder.parent!=(ROOT/'build').resolve() or folder.exists():raise SystemExit('Use a fresh direct build subfolder.')
    folder.mkdir();os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    from studyforge import learning_memory as memory,learning_signals as signals
    from studyforge.db import connect,j,now
    # The old gate differs by these two newly added lines; keep its unchanged
    # regular expressions and behavior rather than inventing a new baseline.
    source=(ROOT/'studyforge/learning_signals.py').read_text(encoding='utf-8')
    node=copy.deepcopy(next(item for item in ast.parse(source).body if isinstance(item,ast.FunctionDef) and item.name=='learning_excerpt'))
    node.name='old_gate'
    node.body=[item for item in node.body if not (isinstance(item,ast.ImportFrom) and item.module=='learning_voice')
        and not (isinstance(item,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='text' for target in item.targets)
                 and 'partition' in ast.unparse(item.value))]
    namespace=dict(vars(signals));module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
    exec(compile(module,'reproduced-old-gate','exec'),namespace)
    quote='我认为高斯定律说明没有净电荷时电场一定为零。'
    own='我不理解高斯定律里的净通量与局部电场有什么区别。'
    cases=[('只贴题干','原题：\n'+quote),('只贴AI回答','> '+quote),
           ('引用外另问','> '+quote+'\n\n我的问题：'+own),
           ('明确自己的理解','我的理解：'+quote),
           ('自己的代码','我的代码：\n\n```python\n# 我认为循环的边界条件还需要解释。\n```'),
           ('引用多段','教材原文：\n'+quote+'\n\n'+quote+'\n\n我的问题：'+own),
           ('普通知识疑问',own),('普通软件操作','请打开工作台，修改背景透明度。')]
    outputs=[{'name':label,'message':text,'before':namespace['old_gate'](text),'after':signals.learning_excerpt(text)} for label,text in cases]
    size=800;source_block=('> '+quote+'\n')*20;raw=source_block+'\n我的问题：'+own
    with connect() as database:
        for i in range(size):
            event=database.execute('INSERT INTO learning_events(event_key,kind,payload_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                ('synthetic:'+str(i),'chat',j({'student_text':raw}),'completed',now(),now())).lastrowid
            database.execute('INSERT INTO learning_event_filters VALUES (?,1,1)',(event,))
            for topic,text in (('外部引用'+str(i),quote),('真实疑问'+str(i),own)):
                database.execute('INSERT INTO learning_insights(event_id,topic,kind,dimension,observation,quote,confidence,created_at,anchors_json) '
                    'VALUES (?,?,?,?,?,?,?,?,?)',(event,topic,'gap','concepts','合成迁移记录',text,'暂定',now(),'[]'))
    actual_connect=memory.connect;changes=[]
    @contextmanager
    def counted():
        with actual_connect() as database:
            initial=database.total_changes
            try:yield database
            finally:changes.append(database.total_changes-initial)
    memory.connect=counted
    try:
        tracemalloc.start();started=time.perf_counter();memory.filter_existing_events()
        first=time.perf_counter()-started;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        samples=[];start_changes=len(changes)
        for _ in range(12):
            started=time.perf_counter();memory.filter_existing_events();samples.append(time.perf_counter()-started)
        assert sum(changes[start_changes:])==0
    finally:memory.connect=actual_connect
    with connect() as database:
        excluded=database.execute('SELECT COUNT(*) FROM learning_insight_evidence_filters WHERE eligible=0').fetchone()[0]
        kept=database.execute('SELECT COUNT(*) FROM learning_insight_evidence_filters WHERE eligible=1').fetchone()[0]
        assert excluded==kept==size
        assert database.execute('SELECT COUNT(*) FROM mastery').fetchone()[0]==0
    files=['studyforge/learning_voice.py','studyforge/learning_signals.py','studyforge/learning_memory.py','studyforge/learning_profile.py','studyforge/db.py']
    report={'passed':True,'real_model_requests':0,'synthetic_events':size,'synthetic_insights':size*2,
        'excluded':excluded,'kept':kept,'migration_seconds':round(first,4),
        'python_tracemalloc_peak_mib':round(peak/1024**2,3),'warm_repeats':len(samples),
        'warm_median_ms':round(statistics.median(samples)*1000,3),'warm_max_ms':round(max(samples)*1000,3),
        'warm_database_changes':0,'cases':outputs,'production':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},
        'limits':'Synthetic local filtering only; tracemalloc excludes native allocations and does not measure total application RAM or end-to-end AI speed.'}
    (folder/'report.json').write_text(j(report),encoding='utf-8');print(j({k:v for k,v in report.items() if k not in ('cases','production')}),flush=True)


if __name__=='__main__':main(sys.argv[1])
