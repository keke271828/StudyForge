"""Explicit live teaching sample. Final answers only; no private reasoning log."""
import asyncio
import json
import os
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'build/teaching-conditions-20261011-1'
TARGET.mkdir(parents=True,exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR']=str(TARGET/'data')
from studyforge.ai import DeepSeekClient, save_settings
from studyforge.teaching_policy import TEACHER_PERSONA, CHAT_RULES, TEACHING_TASK_REMINDER
from studyforge.teaching_styles import style_policy
from studyforge.learning_modes import mode_policy

CASES=[('条件必要性',
 '教材定义数域P为复数的子集，含0、1，并对加、减、乘及非零除数的除法封闭。'
 '是不是每条条件都不能删？特别是“含0”，如果不写就会失去加法单位元吧？'
 '请针对这个理解讲清楚，不布置习题；不要把删一个条件与同时删多个条件混为一谈。'),
 ('参数构造动机',
 r'证明数列极限唯一性时，假设有两个极限a<b。老师取\varepsilon=(b-a)/2。'
 '我不懂为什么可以恰好取一半，不是需要严格小于一半才能使邻域不重叠吗？'
 '为什么定义允许我选这个值，能不能取三分之一？请直观与专业并存，只回答这个卡点，不布置习题。')]

async def main():
    save_settings({'deepseek_model':'deepseek-flash','background_learning_enabled':False,'agent_tools_enabled':False})
    system=TEACHER_PERSONA+CHAT_RULES+mode_policy('deep')+style_policy('balanced')
    client=DeepSeekClient(model='deepseek-flash',effort='high')
    rows=[]
    try:
        for title,question in CASES:
            started=time.perf_counter()
            answer=await client.complete(system,question+TEACHING_TASK_REMINDER)
            (TARGET/(title+'.md')).write_text(answer,encoding='utf-8')
            rows.append({'case':title,'seconds':round(time.perf_counter()-started,3),'characters':len(answer),'status':'completed'})
            (TARGET/'report.json').write_text(json.dumps({'provider':'deepseek','model':'deepseek-flash','effort':'high','results':rows,
                'scope':'Two isolated API teaching samples; no website comparison and no full-course accuracy claim.'},ensure_ascii=False,indent=2),encoding='utf-8')
            print(title+' completed',flush=True)
    finally:await client.close()

if __name__=='__main__':asyncio.run(main())
