/* One lazy, read-only question viewer shared by desktop and paired phone. */
(()=>{
  'use strict';
  let adapter,dialog,sequence=0,controller,catalog,current,origin,record='',next=null,hash=null,loading=false;
  const MAX_PREVIEW=128000;
  const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
  const ui={};
  function same(scope){return scope&&adapter?.scope()===scope;}
  function reset(){sequence++;controller?.abort();controller=null;catalog=current=null;record='';next=hash=null;loading=false;}
  function close(){if(dialog?.open)dialog.close();else reset();}
  function ensure(){
    if(dialog)return;
    dialog=el('dialog',undefined,'homework-reader');dialog.id='homeworkReader';
    dialog.setAttribute('aria-labelledby','homeworkReaderTitle');
    const header=el('header'),heading=el('div');
    heading.append(el('span','作业 · 按题回看','eyebrow'));
    ui.title=el('h2','作业记录');ui.title.id='homeworkReaderTitle';heading.append(ui.title);
    const exit=el('button','关闭');exit.type='button';exit.onclick=close;header.append(heading,exit);
    const tools=el('div',undefined,'homework-reader-tools'),label=el('label','选择题目');
    ui.select=el('select');ui.select.id='homeworkReaderQuestion';ui.select.onchange=()=>load(Number(ui.select.value));label.append(ui.select);
    ui.refresh=el('button','刷新本题');ui.refresh.type='button';ui.refresh.onclick=()=>load(Number(ui.select.value));tools.append(label,ui.refresh);
    ui.status=el('p','', 'homework-reader-status');ui.status.setAttribute('role','status');
    ui.body=el('div',undefined,'homework-reader-body');ui.body.tabIndex=0;
    ui.content=el('div',undefined,'markdown lesson-render');ui.content.id='homeworkReaderContent';ui.body.append(ui.content);
    const footer=el('footer');ui.more=el('button','继续加载本题记录');ui.more.type='button';ui.more.onclick=()=>load(Number(ui.select.value),true);
    ui.ask=el('button','带题号回原对话');ui.ask.type='button';ui.ask.className='primary';ui.ask.onclick=followup;
    ui.repair=el('button','针对这道题再练');ui.repair.type='button';ui.repair.hidden=true;
    ui.repair.onclick=()=>{if(!loading&&current?.repair_reference&&same(origin))
      window.studyforgeRepairPicker.open(current.exercise_set_id,[current.question_number-1],current.repair_reference);};
    const note=el('p','在这里查看已有题目、作答和解析，不会请求 AI。想继续问时，带着题号回到聊天区，再填写问题并发送；原来的草稿会保留。','homework-reader-note');
    footer.append(ui.more,ui.ask,ui.repair,note);dialog.append(header,tools,ui.status,ui.body,footer);document.body.append(dialog);
    dialog.addEventListener('close',()=>{if(!dialog.open)reset();});
  }
  function controls(){
    ui.refresh.disabled=loading||!catalog;ui.ask.disabled=loading||!current?.record_sha256;
    ui.repair.hidden=!current?.repair_reference;ui.repair.disabled=loading;
    ui.more.hidden=next===null;ui.more.disabled=loading||record.length>=MAX_PREVIEW;
    ui.more.textContent=loading?'正在读取…':'继续加载本题记录';
  }
  async function request(path,token,scope){
    const result=await adapter.api(path,{signal:controller.signal});
    if(token!==sequence||!dialog.open||!same(scope))return null;
    return result;
  }
  function path(number,offset=0){
    const params=new URLSearchParams({project_id:catalog.project_id});
    if(number!==undefined)params.set('question_number',String(number));
    if(offset)params.set('offset',String(offset));
    if(offset&&hash)params.set('record_sha256',hash);
    return '/api/homework/'+encodeURIComponent(catalog.attempt_id)+'/reading?'+params;
  }
  async function open(attemptId){
    if(!adapter?.project())return;
    ensure();reset();origin=adapter.scope();const scope=origin,token=++sequence;
    controller=new AbortController();loading=true;ui.title.textContent='作业记录';ui.select.replaceChildren();ui.content.replaceChildren();
    ui.status.textContent='正在读取题目目录…';if(!dialog.open)dialog.showModal();controls();
    try{
      const value=await request('/api/homework/'+encodeURIComponent(attemptId)+'/reading?'+new URLSearchParams({project_id:adapter.project()}),token,scope);
      if(!value)return;
      catalog=value;ui.title.textContent=value.title;
      for(const item of value.questions){const option=el('option','第 '+item.question_number+' 题 · '+item.topic);option.value=item.question_number;ui.select.append(option);}
      if(!value.questions.length){ui.status.textContent='这份题单没有可回看的题目。';loading=false;controls();return;}
      await load(value.questions[0].question_number);
    }catch(error){if(token===sequence&&same(scope)&&error.name!=='AbortError'){loading=false;ui.status.textContent=error.message;controls();}}
  }
  async function load(number,append=false){
    if(!catalog||!same(origin)||append&&(next===null||loading||record.length>=MAX_PREVIEW))return;
    const scope=origin,token=++sequence;controller?.abort();controller=new AbortController();loading=true;
    if(!append){record='';next=hash=null;current=null;ui.content.replaceChildren();ui.body.scrollTop=0;}
    ui.status.textContent='正在读取第 '+number+' 题的已交付记录…';controls();
    try{
      const value=await request(path(number,append?next:0),token,scope);if(!value)return;
      // Never silently join different revisions, even if an unexpected server
      // implementation omits its version guard.
      if(append&&(value.record_sha256!==hash||value.offset!==record.length))throw Error('本题记录已经变化，请点“刷新本题”重新读取。');
      current=value;hash=value.record_sha256;record+=value.text;next=value.next_offset;
      const top=ui.body.scrollTop;adapter.render(ui.content,record);ui.body.scrollTop=top;
      ui.status.textContent=!hash?value.text:next!==null
        ?'已显示 '+record.length+' / '+value.total_characters+' 字；下方还有内容，可能包含题目条件或解析。'+(record.length>=MAX_PREVIEW?'为保持流畅，更多内容请查看完整下载文档。':'可继续加载。')
        :(value.feedback_available?'下面是本题已有的批改和补讲。请留意“待确认”等标注，表示导师还不能确定。':'目前可看原题、你的作答和参考解析，错因分析与补讲还没有完成。');
      if(value.version_notice)ui.status.textContent=value.version_notice+' '+ui.status.textContent;
    }catch(error){if(token===sequence&&same(scope)&&error.name!=='AbortError'){current=null;next=null;ui.status.textContent=error.message;}}
    finally{if(token===sequence){loading=false;controls();}}
  }
  async function followup(){
    if(loading||!current?.record_sha256||!same(origin))return;
    const selected=current,book=catalog;ui.ask.disabled=true;
    try{
      if(!await adapter.go(selected.conversation_id,selected.project_id))return;
      const topic=book.questions.find(q=>q.question_number===selected.question_number)?.topic||'';
      const prefix='关于《'+book.title+'》第 '+selected.question_number+' 题'+(topic?'（'+topic+'）':'')+'，我想继续问：';
      adapter.draft(prefix);close();
    }catch(error){ui.status.textContent=error.message;}
    finally{if(dialog.open)controls();}
  }
  document.addEventListener('click',event=>{const button=event.target.closest('[data-homework-read]');if(button)open(button.dataset.homeworkRead);});
  window.studyforgeHomeworkReader={configure(value){adapter=value;},open,close};
})();
