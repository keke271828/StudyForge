/* Explicit target selection; opening or checking boxes never calls an AI. */
(()=>{
  'use strict';
  let adapter,dialog,catalog,origin,sequence=0,controller;
  const busy=new Set(),ui={};
  const basis={answer_supported_tentative:'根据这次作答初步判断',student_self_report:'你自己的说明 · 未独立验证',unresolved:'还不清楚原因 · 请补充解题思路'};
  const node=(tag,text,cls)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(cls)item.className=cls;return item;};
  function valid(token,scope){return token===sequence&&dialog.open&&adapter.scope()===scope;}
  function close(){if(dialog?.open)dialog.close();}
  function selected(){return [...ui.list.querySelectorAll('input:checked')].map(input=>Number(input.value));}
  function controls(){
    const count=selected().length;ui.count.textContent='已选 '+count+' / '+(catalog?.targets.length||0)+' 题';
    ui.start.textContent=count?'生成选中的 '+count+' 道练习':'请选择需要再练的题';
    ui.start.disabled=!catalog||!count||busy.has(catalog.exercise_set_id);
    ui.all.disabled=!catalog;ui.none.disabled=!catalog;
  }
  function ensure(){
    if(dialog)return;
    dialog=node('dialog',undefined,'repair-picker');dialog.id='repairPicker';dialog.setAttribute('aria-labelledby','repairPickerTitle');
    const header=node('header'),heading=node('div');heading.append(node('span','选择薄弱点，再做一题','eyebrow'));
    ui.title=node('h2','选择要再练的卡点');ui.title.id='repairPickerTitle';heading.append(ui.title);
    const exit=node('button','关闭');exit.type='button';exit.onclick=close;header.append(heading,exit);
    ui.note=node('p','', 'repair-picker-note');ui.status=node('p','', 'repair-picker-status');ui.status.setAttribute('role','status');
    const tools=node('div',undefined,'repair-picker-tools');ui.count=node('strong');ui.all=node('button','全选失分题');ui.none=node('button','清空');
    for(const [button,value] of [[ui.all,true],[ui.none,false]]){button.type='button';button.onclick=()=>{ui.list.querySelectorAll('input').forEach(input=>input.checked=value);controls();};}
    tools.append(ui.count,ui.all,ui.none);ui.list=node('div',undefined,'repair-picker-list');ui.list.id='repairPickerList';ui.list.onchange=controls;
    const footer=node('footer');ui.start=node('button','生成选中的练习','primary');ui.start.id='startSelectedRepair';ui.start.type='button';ui.start.onclick=start;
    footer.append(ui.start,node('p','每选一个薄弱点，就出一道难度相近的新题，提交前不显示答案。使用当前 AI，可能消耗额度；已有合适题单时会直接使用。','repair-picker-note'));
    dialog.append(header,ui.note,tools,ui.status,ui.list,footer);document.body.append(dialog);
    dialog.addEventListener('close',()=>{if(!dialog.open){sequence++;controller?.abort();catalog=null;}});
  }
  async function open(setId,preset=null,expected=null){
    if(!adapter?.project())return;
    ensure();controller?.abort();controller=new AbortController();const token=++sequence,scope=adapter.scope();origin=scope;catalog=null;
    ui.title.textContent='选择要再练的卡点';ui.note.textContent='正在读取这次作答的失分的题目；选择题目不调用模型。';ui.status.textContent='';ui.list.replaceChildren();
    if(!dialog.open)dialog.showModal();controls();
    try{
      const result=await adapter.api('/api/exercises/'+encodeURIComponent(setId)+'/repair-options',{signal:controller.signal});
      if(!valid(token,scope))return;
      if(result.project_id!==adapter.project())throw Error('这份作业不属于当前项目，请返回原项目后再练。');
      if(expected&&(result.expected_submission_id!==expected.submission_id||result.expected_context_signature!==expected.context_signature))
        throw Error('作答、评分或补讲依据已经变化，请先刷新本题，再选择练习。');
      if(preset&&preset.some(index=>!result.targets.some(target=>target.index===index)))throw Error('所选题目前没有可用的错题分析记录，请刷新作业记录。');
      catalog=result;ui.title.textContent=result.title+' · 选择再练范围';ui.note.textContent=result.notice+' 参考难度 '+result.difficulty+'/5。';
      for(const target of result.targets){
        const label=node('label',undefined,'repair-picker-item'),input=node('input');input.type='checkbox';input.value=target.index;input.checked=!preset||preset.includes(target.index);
        const text=node('span'),title=node('strong','原第 '+(target.index+1)+' 题 · '+target.topic);
        text.append(title,node('small','本次 '+target.score+' / 100 · '+(basis[target.basis]||'原因待定位')));label.append(input,text);ui.list.append(label);
      }
      controls();
    }catch(error){if(valid(token,scope)&&error.name!=='AbortError'){ui.status.textContent=error.message;ui.note.textContent='尚未开始生成，可关闭窗口后检查作业状态。';controls();}}
  }
  async function start(){
    if(!catalog||adapter.scope()!==origin)return;
    const indices=selected(),item=catalog,scope=origin,token=sequence;
    if(!indices.length||busy.has(item.exercise_set_id))return;
    busy.add(item.exercise_set_id);controls();ui.status.textContent='正在提交所选 '+indices.length+' 项卡点…';
    try{
      const selection=adapter.selection();
      const payload={...selection,background:true,question_indices:indices,
        expected_submission_id:item.expected_submission_id,expected_context_signature:item.expected_context_signature};
      await adapter.launch(item.exercise_set_id,payload);
      if(valid(token,scope))close();
    }catch(error){if(valid(token,scope))ui.status.textContent=error.message;}
    finally{busy.delete(item.exercise_set_id);if(valid(token,scope))controls();}
  }
  window.studyforgeRepairPicker={configure(value){adapter=value;},open,close};
})();
