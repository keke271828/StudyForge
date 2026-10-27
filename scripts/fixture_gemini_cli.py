"""Offline subprocess fixture for desktop acceptance; never contacts Google."""
import json
import os
import sys
import time
from pathlib import Path


def main():
    arguments=sys.argv[1:]
    model=arguments[arguments.index('-m')+1]
    raw=sys.stdin.buffer.read().decode('utf-8')
    body=json.loads(raw.split('任务输入：\n',1)[1])
    folder=Path(os.environ['STUDYFORGE_PERMISSION_CASE']).parent
    log=folder/'cli-events.jsonl'
    def record(phase):
        with log.open('a',encoding='utf-8') as file:
            file.write(json.dumps({'phase':phase,'model':model,'source_read':'尾部论据' in raw,'pid':os.getpid()})+'\n')
    def emit(packet):print(json.dumps(packet,ensure_ascii=False),flush=True)
    record('started')
    if model=='cli-quota-fixture':
        emit({'type':'result','status':'error','error':{'type':'RESOURCE_EXHAUSTED','message':'quota PRIVATE_CREDENTIAL'}})
        sys.exit(1)
    message=next((row.get('content','') for row in reversed(body['messages']) if row['role']=='user'),'')
    finished=body['messages'][-1]['role']=='tool'
    calls=[]
    if message.startswith('账号审批测试') and not finished:
        text='请审批本次文件修改，批准后继续原任务。'
        calls=[{'name':'sf_write_text','arguments':{'path':str(folder/'approved.txt'),'text':'账号审批后已保存','overwrite':True}}]
    elif finished:text='账号已按审批结果完成文件修改。'
    elif message.startswith('账号取消测试'):
        emit({'type':'message','role':'assistant','delta':True,'content':'{"content":"取消测试正在逐步生成正文。'})
        for _ in range(1000):
            (folder/'cli-heartbeat.txt').write_text(str(time.monotonic()))
            time.sleep(.05)
        return
    else:
        text='账号实时讲解：先明确概念，再说明证据与边界。\n\n公式：\\(F=ma\\)。\n\n## 系统性总结\n共同原因与外部效度需要分开理解。尾部论据必须依据完整原文。'
    envelope=json.dumps({'content':text,'tool_calls':calls},ensure_ascii=True)
    for offset in range(0,len(envelope),14):
        emit({'type':'message','role':'assistant','delta':True,'content':envelope[offset:offset+14]})
        time.sleep(.035)
    record('completed')
    emit({'type':'result','status':'success'})


if __name__=='__main__':main()
