"""Real inputs, with/without a user-selected reference; unchanged model/rules."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
CASES=[
 {'id':'epsilon','title':'数学追问：任意正数与特例','role':'tutor','style':'balanced','mode':'deep',
  'source':'数列极限定义：对任意ε>0，存在N使n>N时|x_n−a|<ε。反证设极限为a,b且a<b，可取ε=(b−a)/2。',
  'target':'极限定义对每个正数ε都成立；因为a<b，所以(b−a)/2是正数，可以使用这一特例。两个开邻域因此不相交。',
  'quote':'极限定义对每个正数ε都成立；因为a<b，所以(b−a)/2是正数，可以使用这一特例。',
  'later':'合并两个门槛时取N=max{N₁,N₂}，这样n>N会同时超过它们，两个条件才同时成立。',
  'question':'这一步是不是给原定义额外加了限制？我还没弄懂，请就这一处说明为什么可以，不从头重讲证明，不出题。',
  'checks':['区分全称命题取特例与改写定义','a<b保证正数取值合法','不只解释最大门槛而遗漏被选句','不把半径选择当唯一方法']},
 {'id':'python','title':'编程追问：共享对象何时分开','role':'tutor','style':'clear','mode':'deep',
  'source':'Python代码尚未运行：a=[[0]]*2; a[0]=[7]; a[1].append(8)。列表乘法复制已有引用；下标赋值只替换一个槽位。',
  'target':'最初两个槽位共享同一个[0]。执行a[0]=[7]后，第0个槽位指向新的[7]，第1个仍指向旧的[0]，所以最后a是[[7],[0,8]]。',
  'quote':'执行a[0]=[7]后，第0个槽位指向新的[7]，第1个仍指向旧的[0]',
  'later':'如果改成a[0].append(7)，那是在修改现有内层对象，两个槽位仍指向它。这里只是另一个对照操作，不是原代码。',
  'question':'这里为什么一个会变、另一个却不跟着变？我卡在这句，请沿这个操作讲对象关系，给出原代码静态结果，不讲整套内存管理，不出题。',
  'checks':['回答选中下标赋值，不将后来的append对照替换原代码','初始共享判断保留','原结果[[7],[0,8]]','静态推演不声称实机执行']},
 {'id':'energy','title':'文档承接：旧AI的时间导数理由错误','role':'lecture','style':'balanced','mode':'deep',
  'source':'给定模型m,k>0，x=x(t)，v=x′(t)，m v′=−kx，E(x,v)=mv²/2+kx²/2。变量沿轨迹依赖时间。原资料不包含其他外力模型。',
  'target':'E没有显式t，所以沿轨迹dE/dt直接为0，不需要使用运动方程。另有∂E/∂x=kx、∂E/∂v=mv。',
  'quote':'E没有显式t，所以沿轨迹dE/dt直接为0，不需要使用运动方程。',
  'later':'两个形式偏导分别是kx和mv。计算偏导时另一变量保持不变。',
  'question':'这句话的理由是不是有问题？请核对后把这一处整理成可独立读懂的简短讲解，说明真正依据和条件，最后总结，不扩展新模型，不出题。',
  'checks':['直接更正旧AI理由','显式时间偏导0不等于沿轨迹时间导数0','dE/dt=kxv+mv v′=v(kx+mv′)=0，最后一步使用运动方程','不新增外力或哈密顿模型']},
]


async def main(name):
 out=ROOT/'build'/name
 if out.exists() and any(out.iterdir()):raise SystemExit('Use a fresh folder.')
 out.mkdir(parents=True);os.environ['STUDYFORGE_DATA_DIR']=str(out/'data');os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
 from studyforge import ai,server,conversations,message_focus
 from studyforge.db import create_project,execute,j,now,one,uid,connect
 from studyforge.materials import read_original_sources
 from studyforge.learning import learning_requirements
 from scripts.diagnose_deepseek_speed import traced_class
 ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':False,'agent_network_enabled':False,'background_learning_enabled':False,'library_reference_mode':'off','model_concurrency':2})
 cases=[]
 for case in CASES:
  p=create_project('原句追问实测 · '+case['id']);path=out/(case['id']+'.txt');path.write_text(case['source'],encoding='utf-8');sid=uid()
  execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',(sid,p['id'],path.name,'.txt',str(path),'[]','ready',now()))
  requests={}
  for arm in ('baseline','reference'):
   c=conversations.create(p['id'],'deepseek','deepseek-flash','high');target=uid()
   for role,text,mid in [('user','请先解释这段原材料。',uid()),('assistant',case['target'],target),('user','刚才还有哪一点要注意？',uid()),('assistant',case['later'],uid())]:
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,c['id'],role,text,now()))
   begin=case['target'].index(case['quote'])
   ref=message_focus.MessageReference(message_id=target,content_sha256=hashlib.sha256(case['target'].encode()).hexdigest(),selection={'start':begin,'end':begin+len(case['quote']),'text':case['quote']}) if arm=='reference' else None
   captured=[]
   class Capture:
    model='deepseek-flash';effort='high'
    async def agent_stream(self,messages):captured.append(copy.deepcopy(messages));yield 'final','受控捕获，不是实际输出。'
    async def complete(self,system,user,**kwargs):captured.append([{'role':'system','content':system},{'role':'user','content':user}]);return '## 系统性总结\n受控捕获。'
   if case['role']=='tutor':
    with patch.object(server,'DeepSeekClient',lambda *a,**k:Capture()),patch.object(server,'client_for',lambda *a,**k:Capture()):
     response=await server._chat_response_impl(server.ChatIn(project_id=p['id'],conversation_id=c['id'],provider='deepseek',model='deepseek-flash',reasoning_effort='high',source_ids=[sid],text=case['question'],reply_reference=ref,explanation_style=case['style'],learning_mode=case['mode']))
     lines=[line async for line in response.body_iterator];assert not any(b'"error"' in line for line in lines),lines
   else:
    mid=uid()
    with connect() as d:
     d.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,c['id'],'user',case['question'],now()));message_focus.save(d,mid,c['id'],message_focus.resolve(ref,p['id'],c['id'],d))
    history=server.conversation_history(c['id'],p['id'],[sid]);records=read_original_sources([one('SELECT * FROM sources WHERE id=?',(sid,))]);digest,_=ai._assemble_source_digest(records,records,False)
    await ai.generate_explanation(Capture(),digest,3,[],style=case['style'],learning_mode=case['mode'],requirements=learning_requirements(history,'按上面这次追问整理讲解。'))
   assert len(captured)==1;requests[arm]=captured[0]
  cases.append(case|{'requests':requests})
 (out/'cases.json').write_text(j({'cases':cases,'model':'deepseek-flash','effort':'high','planned_requests':6,'same_rules':True,'difference':'explicit_reference_information'}),encoding='utf-8')
 cls=traced_class();results=[]
 for case in cases:
  async def sample(arm):
   client=cls('deepseek-flash',effort='high');start=time.perf_counter();row={'case':case['id'],'arm':arm,'role':case['role']}
   try:
    answer=''
    async with asyncio.timeout(240):
     async for kind,value in client.agent_stream(case['requests'][arm]):
      if kind=='final':answer=value
    assert answer.strip();file=case['id']+'-'+arm+'-final.md';(out/file).write_text(answer,encoding='utf-8');row.update(status='completed',answer_file=file,output_characters=len(answer),answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
   except Exception as exc:row.update(status='failed',error_type=type(exc).__name__)
   finally:await client.close()
   row.update(seconds=time.perf_counter()-start,model_requests=len(client.traces),http_attempts=[t.public() for t in client.traces]);results.append(row);(out/'results.json').write_text(j(results),encoding='utf-8');print(json.dumps({k:row[k] for k in ('case','arm','status','seconds','model_requests')}),flush=True)
  await asyncio.gather(*(sample(arm) for arm in ('baseline','reference')))


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
