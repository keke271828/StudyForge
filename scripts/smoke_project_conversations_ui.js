const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const casePath=process.env.STUDYFORGE_WORKSPACE_UI_CASE,root=path.dirname(casePath),data=JSON.parse(fs.readFileSync(casePath,'utf8'));
const phase=process.env.STUDYFORGE_WORKSPACE_UI_PHASE||'1',stateFile=path.join(root,'ui-state.json');
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[];const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){return win.webContents.executeJavaScript(code);}
async function until(code){for(let n=0;n<220;n++){if(await run(code))return;await sleep(100);}throw new Error('Timeout: '+code);}
function calls(){return JSON.parse(fs.readFileSync(path.join(root,'requests.json'),'utf8'));}
async function snapshot(name){await sleep(200);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function options(){return run(`({style:currentExplanationStyle(),language:$('outputLanguage').value,mode:currentLearningMode(),review:$('reviewMode').value})`);}
async function setOptions(style,language,mode,review){
  const count=calls().length,reading=await run('state.reading?.reading_id');
  await run(`(async()=>{await applyExplanationStyle('${style}');await applyOutputLanguage('${language}');applyLearningMode('${mode}');await learningModeSave;await applyReviewMode('${review}');await flushConversation();})()`);
  assert.equal(calls().length,count,'Changing teaching options invoked a model');
  assert.equal(await run('state.reading?.reading_id'),reading,'Changing teaching options discarded original reading');
}
function checkRequest(style,language,mode){
  const labels={clear:'通俗清晰',balanced:'直观与专业并重',academic:'学术专业',zh:'中文',bilingual:'中英双语',en:'英语',overview:'概览',deep:'精学',research:'研究'};
  const system=calls().at(-1).messages[0].content;
  for(const [field,value] of [['风格',style],['语言',language],['模式',mode]])assert.ok(system.includes('当前'+(field==='模式'?'学习':'讲解')+field+'：'+labels[value]),'Actual request missing '+field);
}
async function checkNotes(label){
  const before=await run(`(async()=>{await flushConversation();return {html:$('messages').innerHTML,scroll:$('messages').scrollTop,draft:$('prompt').value,reading:state.reading.reading_id,rows:(await api('/api/conversations/'+state.conversation+'/messages?project_id='+state.project.id)).messages};})()`);
  const count=calls().length;
  await run(`$('showReadingNotes').click()`);
  assert.equal(await run(`$('readingNotesDialog').open`),true);
  assert.equal(await run(`$('readingNotesText').textContent.includes('笔记范围：'+${JSON.stringify(label)})`),true);
  assert.equal(await run(`$('readingNotesText').dataset.rawText===state.reading.notes`),true);
  assert.ok(await run(`$('readingNotesText').querySelectorAll('.katex').length>=2`),'Notes math was not rendered');
  assert.equal(await run(`!!$('readingNotesText').querySelector('table') && !!$('readingNotesText').querySelector('pre code') && !!$('readingNotesText').querySelector('.lesson-quote')`),true);
  assert.equal(await run(`$('readingNotesText').textContent.includes('行 1-2')`),true);
  await run(`$('readingNotesBody').scrollTop=320`);
  const position=await run(`$('readingNotesBody').scrollTop`);assert.ok(position>100);
  await run(`$('returnFromReadingNotes').click();$('showReadingNotes').click()`);
  assert.ok(Math.abs(await run(`$('readingNotesBody').scrollTop`)-position)<2,'Reopening lost the note reading position');
  win.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});
  win.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'});
  await until(`!$('readingNotesDialog').open`);
  await run(`$('showReadingNotes').click()`);
  assert.ok(Math.abs(await run(`$('readingNotesBody').scrollTop`)-position)<2,'Escape lost the note reading position');
  // Simulate denied web Clipboard permission and verify the existing fallback
  // selects inside the active modal. Do not overwrite the user's clipboard.
  await run(`window.__originalClipboard=Object.getOwnPropertyDescriptor(navigator,'clipboard');window.__originalCopy=document.execCommand;Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('Write permission denied')}}});document.execCommand=command=>{window.__notesCopied=document.activeElement.value;window.__notesCopyInModal=!!document.activeElement.closest('#readingNotesDialog') && document.activeElement.selectionEnd-document.activeElement.selectionStart===state.reading.notes.length;return command==='copy';};$('copyReadingNotes').click()`);
  await until(`$('readingNotesCopyStatus').textContent==='笔记已复制'`);
  assert.equal(await run('window.__notesCopyInModal'),true);
  assert.equal(await run('window.__notesCopied===state.reading.notes'),true);
  await run(`if(window.__originalClipboard)Object.defineProperty(navigator,'clipboard',window.__originalClipboard);else delete navigator.clipboard;document.execCommand=window.__originalCopy;delete window.__notesCopied;delete window.__notesCopyInModal;`);
  await run(`$('closeReadingNotes').click()`);
  assert.equal(await run(`document.activeElement.id`),'showReadingNotes');
  assert.deepEqual(await run(`(async()=>{return {html:$('messages').innerHTML,scroll:$('messages').scrollTop,draft:$('prompt').value,reading:state.reading.reading_id,rows:(await api('/api/conversations/'+state.conversation+'/messages?project_id='+state.project.id)).messages};})()`),before,'Opening notes changed chat, draft or persisted messages');
  assert.equal(calls().length,count,'Opening notes called a model');
}
app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1480,height:960,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
  try{
    await win.loadURL(data.url);await until('state.ready && state.conversation && !conversationUI.restoring && state.deepseekCatalog');
    if(phase==='1'){
      assert.equal(await run('state.conversation'),data.legacy_id);
      assert.equal(await run(`$('messages').textContent.includes('保留升级前的聊天记录')`),true);
      await run(`$('newConversation').click()`);
      await until(`state.conversation!=='${data.legacy_id}' && !$('newConversation').disabled && !conversationUI.restoring`);
      const a=await run('state.conversation');
      assert.equal(await run('state.selected.size'),0);
      await run(`setSourceSelected('${data.sources[0]}',true);setSourceSelected('${data.sources[1]}',true);ensureReading()`);
      const readingA=await run('state.reading.reading_id');
      await setOptions('clear','zh','overview','express');
      await run(`$('prompt').value='只属于AB对话的要求';$('sendMessage').onclick()`);
      checkRequest('clear','zh','overview');
      await checkNotes('AB');
      await run(`$('showReadingNotes').click();$('readingNotesBody').scrollTop=0`);
      await snapshot('reading-notes-independent');
      await run(`setSourceSelected('${data.sources[0]}',false)`);
      assert.equal(await run(`$('readingNotesDialog').open`),false,'Old notes stayed visible after source change');
      await run(`setSourceSelected('${data.sources[0]}',true);ensureReading()`);
      await run(`$('showReadingNotes').click()`);
      await run(`showView('sources')`);
      assert.equal(await run(`$('readingNotesDialog').open`),false);
      await run(`showView('study')`);
      await run('openKnowledge()');await run('buildKnowledge()');
      const mapA=await run('knowledgeState.row?.id');assert.ok(mapA);
      await run(`$('closeKnowledge').click()`);
      const b=await run(`(async()=>{await createConversation();return state.conversation;})()`);
      assert.equal(await run('state.selected.size'),0);
      await run(`setSourceSelected('${data.sources[1]}',true);setSourceSelected('${data.sources[2]}',true);ensureReading()`);
      await setOptions('academic','en','research','fast');
      await run(`$('prompt').value='只属于BC对话的要求';$('sendMessage').onclick()`);
      checkRequest('academic','en','research');
      await checkNotes('BC');
      await run(`(async()=>{beginNavigationRename('conversation',state.conversation);navigationUI.editing.input.value='B与C的独立讨论';await commitNavigationRename();})()`);
      await until(`$('conversationTitle').textContent==='B与C的独立讨论'`);
      await run(`$('prompt').value='B对话尚未发出的草稿';$('prompt').dispatchEvent(new Event('input'));`);
      const readCalls=calls().filter(row=>row.kind==='reading').length;
      await run(`$('showReadingNotes').click();selectConversation('${a}')`);
      assert.equal(await run(`$('readingNotesDialog').open`),false);
      await checkNotes('AB');
      assert.deepEqual(await options(),{style:'clear',language:'zh',mode:'overview',review:'express'});
      assert.equal(await run(`$('messages').textContent.includes('只属于BC对话')`),false);
      assert.deepEqual(await run('[...state.selected].sort()'),data.sources.slice(0,2).sort());
      assert.equal(await run('state.reading.reading_id'),readingA);
      await run('openKnowledge()');assert.equal(await run('knowledgeState.row.id'),mapA);await run(`$('closeKnowledge').click()`);
      assert.equal(calls().filter(row=>row.kind==='reading').length,readCalls);
      await run(`showView('sources');showView('settings');showView('study');`);
      assert.equal(await run(`$('messages').textContent.includes('只属于AB对话')`),true);
      await run(`$('withExercises').checked=false;$('outputFormat').value='docx';$('generate').onclick()`);
      await run(`$('showReadingNotes').click();selectProject({id:'${data.other_project_id}',name:'另一个项目'})`);
      assert.equal(await run(`$('readingNotesDialog').open`),false,'Old notes stayed visible after project switch');
      assert.equal(await run(`$('artifacts').querySelectorAll('[data-artifact]').length`),0);
      await until(`(async()=>{const jobs=await api('/api/projects/${data.project_id}/jobs');return jobs.some(row=>row.kind==='generate'&&['completed','failed'].includes(row.status));})()`);
      assert.equal(await run(`$('artifacts').querySelectorAll('[data-artifact]').length`),0);
      await run(`selectProject({id:'${data.project_id}',name:'跨学科学习项目'})`);
      const artifact=await run(`(async()=>{await refreshSources();await refreshArtifacts();const rows=await api('/api/projects/${data.project_id}/artifacts');return rows.find(row=>row.kind==='explanation');})()`);
      assert.ok(artifact,'Generated file missing');
      assert.equal(artifact.metadata.explanation_style,'clear');
      assert.equal(artifact.metadata.output_language,'zh');
      assert.equal(artifact.metadata.learning_mode,'overview');
      const question=await run(`(async()=>{const q=await api('/api/lesson-feedback/by-job/${artifact.metadata.generation_job_id}');await selectConversation('${a}');return q;})()`);
      await setOptions('balanced','bilingual','deep','strict');
      await run(`openLessonFeedback('${question.id}')`);
      assert.deepEqual(await options(),{style:'clear',language:'zh',mode:'overview',review:'strict'},'Questionnaire did not restore original teaching choices');
      await setOptions('clear','zh','overview','express');
      const ref=await run(`state.sources.find(row=>row.artifact_id==='${artifact.id}')`);assert.ok(ref);
      assert.equal(await run(`state.selected.has('${ref.id}')`),false);
      const d=await run(`(async()=>{await createConversation();setSourceSelected('${ref.id}',true);await ensureReading();$('prompt').value='请解释成果末尾唯一证据';await $('sendMessage').onclick();return state.conversation;})()`);
      assert.ok(calls().at(-1).messages[0].content.includes('成果末尾唯一证据：独立引用无需重新导入'));
      await run(`(async()=>{showView('artifacts');await refreshArtifacts();document.querySelector('[data-rename-artifact="${artifact.id}"]').click();const form=document.querySelector('[data-artifact-rename-form="${artifact.id}"]');form.querySelector('input').value='可直接引用的讲解';form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));})()`);
      await until(`state.sources.some(row=>row.artifact_id==='${artifact.id}'&&row.name.includes('可直接引用的讲解'))`);
      await run(`selectProject({id:'${data.other_project_id}',name:'另一个项目'})`);
      assert.equal(await run(`$('artifacts').querySelectorAll('[data-artifact]').length`),0);
      assert.equal(await run('state.sources.length'),0);
      assert.equal(await run(`$('messages').textContent.includes('只属于AB')`),false);
      await run(`selectProject({id:'${data.project_id}',name:'跨学科学习项目'});`);
      await run(`selectConversation('${b}')`);
      assert.deepEqual(await options(),{style:'academic',language:'en',mode:'research',review:'fast'});
      assert.equal(await run(`$('prompt').value`),'B对话尚未发出的草稿');
      await run('prepareDesktopExit()');await snapshot('workbench-multiple-conversations');
      fs.writeFileSync(stateFile,JSON.stringify({a,b,d,readingA,mapA,artifact:artifact.id,reference:ref.id,readingCalls:calls().filter(row=>row.kind==='reading').length,allCalls:calls().length}));
    }else{
      const saved=JSON.parse(fs.readFileSync(stateFile,'utf8'));
      assert.equal(await run('state.project.id'),data.project_id);
      assert.equal(await run('state.conversation'),saved.b);
      assert.deepEqual(await options(),{style:'academic',language:'en',mode:'research',review:'fast'});
      assert.equal(await run(`$('prompt').value`),'B对话尚未发出的草稿');
      assert.equal(await run(`$('conversationTitle').textContent`),'B与C的独立讨论');
      assert.deepEqual(await run('[...state.selected].sort()'),data.sources.slice(1).sort());
      assert.equal(await run(`$('messages').textContent.includes('只属于AB')`),false);
      await checkNotes('BC');
      await run(`(async()=>{await selectConversation('${saved.a}');await openKnowledge();})()`);
      assert.equal(await run('state.reading.reading_id'),saved.readingA);
      assert.equal(await run('knowledgeState.row.id'),saved.mapA);
      await run(`$('closeKnowledge').click()`);
      await checkNotes('AB');
      assert.deepEqual(await options(),{style:'clear',language:'zh',mode:'overview',review:'express'});
      assert.equal(calls().length,saved.allCalls,'Restore called a model after actual backend restart');
      await run(`(async()=>{await selectConversation('${saved.d}');showView('artifacts');await refreshArtifacts();document.querySelector('[data-delete-artifact="${saved.artifact}"]').click();document.querySelector('[data-delete-artifact="${saved.artifact}"]').click();})()`);
      await until(`!state.sources.some(row=>row.id==='${saved.reference}')`);
      await run(`(async()=>{await selectConversation('${saved.a}');await selectConversation('${saved.d}');})()`);
      assert.equal(await run('state.selected.size'),0);
      assert.equal(await run(`$('messages').textContent.includes('请解释成果末尾唯一证据')`),true);
      await run(`(async()=>{await selectConversation('${saved.b}');showView('study');})()`);
      win.setSize(1060,820);await snapshot('workbench-after-restart-small');
      await run(`$('showReadingNotes').click()`);await snapshot('reading-notes-small');
      const noteBounds=await run(`({width:$('readingNotesDialog').getBoundingClientRect().width,height:$('readingNotesDialog').getBoundingClientRect().height,overflow:document.documentElement.scrollWidth-innerWidth,footer:$('returnFromReadingNotes').getBoundingClientRect().bottom,viewport:innerHeight})`);
      assert.ok(noteBounds.overflow<3 && noteBounds.footer<=noteBounds.viewport && noteBounds.width<1060 && noteBounds.height<820,'Notes overflow: '+JSON.stringify(noteBounds));
      win.setSize(560,720);await snapshot('reading-notes-narrow');
      assert.ok(await run(`$('returnFromReadingNotes').getBoundingClientRect().bottom<=innerHeight && document.documentElement.scrollWidth<=innerWidth+2`));
      await run(`$('closeReadingNotes').click()`);win.setSize(1060,820);
      await run(`document.querySelector('.advanced-generation').open=true`);await snapshot('teaching-options-small');
      const optionBounds=await run(`(()=>{const r=document.querySelector('.advanced-grid').getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,viewport:innerHeight,scrollable:getComputedStyle(document.querySelector('.advanced-grid')).overflowY,hints:['explanationStyleHint','outputLanguageHint','reviewModeHint'].every(id=>$(id).textContent.length>10)};})()`);
      assert.ok(optionBounds.top>=0 && optionBounds.bottom<=optionBounds.viewport && optionBounds.hints,'Teaching options are clipped: '+JSON.stringify(optionBounds));
      await run(`document.querySelector('.advanced-generation').open=false`);
      const bounds=await run(`({overflow:document.documentElement.scrollWidth-innerWidth,history:document.querySelectorAll('.conversation-item').length,composer:$('prompt').getBoundingClientRect().height})`);
      assert.ok(bounds.overflow<3,'Horizontal overflow: '+bounds.overflow);assert.ok(bounds.composer>30);
      assert.deepEqual(errors,[]);
      fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({success:true,actual_backend_restart:true,independent_chats:true,independent_selections:true,restored_draft:true,no_restore_model_requests:true,knowledge_reused:true,artifact_full_file_reference:true,artifact_project_isolation:true,rename_delete_sync:true,notes_separate_from_chat:true,notes_reopen_keeps_position:true,notes_restore_without_model:true,notes_markdown_math_sources:true,notes_copy_permission_fallback:true,notes_narrow_layout:true,teaching_options_actual_requests:true,teaching_options_no_reread:true,teaching_options_per_chat_restart:true,questionnaire_original_style_language_mode:true,teaching_options_small_layout:true,bounds,noteBounds,optionBounds},null,2));
    }
    assert.deepEqual(errors,[]);app.exit(0);
  }catch(error){await snapshot('failure-phase-'+phase);fs.writeFileSync(path.join(root,'failure-phase-'+phase+'.txt'),error.stack+'\n'+errors.join('\n'));console.error(error);app.exit(1);}
});
