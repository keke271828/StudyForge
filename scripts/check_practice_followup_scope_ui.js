/* Exercise a real conversation switch while one legacy lookup is delayed. */
module.exports=async win=>win.webContents.executeJavaScript('('+async function(){
 const original=api,project=state.project,conversation=state.conversation,draft=$('prompt').value;
 const button=document.createElement('button');button.type='button';button.dataset.practiceTutor='scope-local';document.body.append(button);
 const tick=()=>new Promise(resolve=>setTimeout(resolve,80)),checks=[];
 let release=null,hold='';
 const worksheet={id:'scope-local',project_id:project.id,title:'LEGACY_SCOPE_MARKER',questions:[{index:0,topic:'论证',question:'只解释这道已提交的练习。'}],homework:null};
 const records=[{grade:{feedback:['已有反馈'],diagnostics:[]}}];
 try{
  api=async function(path,options){
   if(path==='/api/exercises/scope-local')return hold==='set'?new Promise(resolve=>release=resolve):worksheet;
   if(path==='/api/exercises/scope-local/submissions')return hold==='records'?new Promise(resolve=>release=resolve):records;
   return original(path,options);
  };
  button.click();await tick();
  if(!$('prompt').value.includes('LEGACY_SCOPE_MARKER'))throw Error('Same-chat legacy follow-up no longer prefills a question');
  checks.push('same-conversation legacy records keep their existing explicit follow-up');
  $('prompt').value=draft;$('prompt').dispatchEvent(new Event('input',{bubbles:true}));
  const other=await original('/api/projects/'+project.id+'/conversations',jsonOptions('POST',{provider:'deepseek'}));
  hold='set';button.click();await tick();if(!release)throw Error('The lookup was not held');
  await selectConversation(other.id);$('prompt').value='新对话里的草稿不得混入旧反馈';$('prompt').dispatchEvent(new Event('input',{bubbles:true}));
  release(worksheet);await tick();
  if($('prompt').value!=='新对话里的草稿不得混入旧反馈')throw Error('Late exercise feedback contaminated a different conversation draft');
  checks.push('a delayed legacy lookup cannot append its feedback after a real conversation switch');
  await selectConversation(conversation);hold='records';release=null;button.click();await tick();
  if(!release)throw Error('The submission lookup was not held');
  await selectConversation(other.id);$('prompt').value='成绩读取也不能写入另一个对话';$('prompt').dispatchEvent(new Event('input',{bubbles:true}));
  release(records);await tick();
  if($('prompt').value!=='成绩读取也不能写入另一个对话')throw Error('Late submission feedback contaminated another chat');
  checks.push('the second asynchronous submission lookup has the same conversation guard');
  await selectConversation(conversation);hold='set';release=null;button.click();await tick();
  const anotherProject=(await original('/api/projects')).find(row=>row.id!==project.id);
  await selectProject(anotherProject);$('prompt').value='其他项目的草稿保持独立';$('prompt').dispatchEvent(new Event('input',{bubbles:true}));
  release(worksheet);await tick();
  if($('prompt').value!=='其他项目的草稿保持独立')throw Error('Late feedback crossed a project boundary');
  checks.push('a delayed exercise lookup cannot insert feedback into another project');
  return {passed:true,cases:checks};
 }finally{
  api=original;button.remove();
  if(state.project?.id!==project.id)await selectProject(project);
  if(state.conversation!==conversation)await selectConversation(conversation);
  $('prompt').value=draft;$('prompt').dispatchEvent(new Event('input',{bubbles:true}));
 }
}.toString()+')()');
