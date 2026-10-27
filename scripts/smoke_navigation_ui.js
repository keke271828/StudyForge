const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const casePath=process.env.STUDYFORGE_NAVIGATION_CASE,root=path.dirname(casePath),data=JSON.parse(fs.readFileSync(casePath,'utf8'));
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],checks=[],pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){try{return await win.webContents.executeJavaScript(code);}catch(error){throw new Error(code.slice(0,200)+'\n'+error.stack);}}
async function until(code){for(let n=0;n<150;n++){if(await run(code))return;await pause(100);}throw new Error('Timeout: '+code+'\n'+errors.join('\n'));}
async function snapshot(name){await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});await pause(350);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG());}
async function key(code){win.webContents.sendInputEvent({type:'keyDown',keyCode:code});win.webContents.sendInputEvent({type:'keyUp',keyCode:code});await pause(100);}
async function context(kind,id){
  const rect=await run(`(()=>{const row=navigationElement(${JSON.stringify(kind)},${JSON.stringify(id)});row.scrollIntoView({block:'nearest'});const r=row.getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`);
  win.webContents.sendInputEvent({type:'mouseDown',button:'right',...rect});win.webContents.sendInputEvent({type:'mouseUp',button:'right',...rect});
  await until(`!$('navigationContext').hidden`);
}
async function choose(action){await run(`document.querySelector('[data-nav-menu=${action}]').click()`);await pause(100);}
async function rename(kind,id,name){
  await context(kind,id);await choose('rename');
  await run(`navigationUI.editing.input.value=${JSON.stringify(name)};navigationUI.editing.input.dispatchEvent(new Event('input',{bubbles:true}));`);
  await key('Return');await until('!navigationUI.editing');
  await until(`(navigationItem(${JSON.stringify(kind)},${JSON.stringify(id)}).name||navigationItem(${JSON.stringify(kind)},${JSON.stringify(id)}).title)===${JSON.stringify(name)}`);
}
async function rows(id){return run(`navigationItem('project',${JSON.stringify(id)}).conversations.map(row=>row.id)`);}
async function viewRows(id){return run(`(()=>{const folder=[...$('projects').children].find(node=>node.dataset.folder===${JSON.stringify(id)});return [...folder.querySelectorAll('[data-nav-kind=conversation]')].map(row=>row.dataset.navId);})()`);}
async function drop(kind,id,target){
  await run(`(()=>{const from=navigationElement('${kind}','${id}'),to=navigationElement('${kind}','${target}');const transfer=new DataTransfer(),r=to.getBoundingClientRect();from.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:transfer}));to.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer,clientY:r.top+1}));to.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer,clientY:r.top+1}));})()`);
  await run('navigationSave');await until('!navigationUI.dragging');
}
app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1520,height:960,webPreferences:{contextIsolation:true,sandbox:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error')errors.push(event.message);});
  await win.loadURL(data.url);await until('Boolean(state.ready&&state.project&&!state.projectLoading&&!conversationUI.restoring&&navigationUI.loaded)');
  if(data.phase===1){
    assert.equal(await run('state.conversation'),data.chats[0]);
    await run(`expandNavigation('${data.other}',true)`);await run('navigationSave');
    const before=await viewRows(data.project);
    for(const id of [data.chats[2],data.chats[1],data.chats[0]])await run(`selectConversation('${id}')`);
    assert.deepEqual(await viewRows(data.project),before);checks.push('Selecting a chat preserves its row position');
    await run(`$('navigationSort').value='recent';$('navigationSort').dispatchEvent(new Event('change'));`);await run('navigationSave');
    const recent=await viewRows(data.project);await run(`selectConversation('${data.chats[2]}');`);assert.deepEqual(await viewRows(data.project),recent);
    await run(`selectConversation('${data.chats[0]}')`);await run(`$('navigationSort').value='manual';$('navigationSort').dispatchEvent(new Event('change'));`);await run('navigationSave');
    checks.push('Recent-message sorting ignores opening and renaming');
    const draft=await run(`$('prompt').value`);
    await rename('conversation',data.foreign,'权力与规训的概念边界');
    assert.equal(await run('state.project.id'),data.project);assert.equal(await run('state.conversation'),data.chats[0]);assert.equal(await run(`$('prompt').value`),draft);
    checks.push('Native right-click renames inactive chat without switching context');
    await context('conversation',data.chats[0]);await choose('rename');
    await run(`navigationUI.editing.input.value='如何想到这个证明';navigationUI.editing.input.setSelectionRange(3,6);`);
    const editing=await run(`(async()=>{const input=navigationUI.editing.input;await refreshNavigation();await refreshConversations();return{same:input===navigationUI.editing.input,focused:document.activeElement===input,value:input.value,start:input.selectionStart,end:input.selectionEnd};})()`);
    assert.deepEqual(editing,{same:true,focused:true,value:'如何想到这个证明',start:3,end:6});
    await key('Return');await until('!navigationUI.editing');checks.push('Polling preserves inline editor focus, text and selection');
    await rename('project',data.project,'数学 · 证明与构造');
    await context('conversation',data.chats[1]);await choose('pin');await until(`navigationItem('conversation','${data.chats[1]}').pinned===1`);
    assert.equal((await viewRows(data.project))[0],data.chats[1]);
    await drop('conversation',data.chats[0],data.chats[2]);
    assert.deepEqual(await viewRows(data.project),[data.chats[1],data.chats[0],data.chats[2]]);checks.push('Pin and drag persist a real backend order');
    await run(`$('navigationSearch').value='规训';$('navigationSearch').dispatchEvent(new Event('input'));`);
    assert.equal(await run(`$('projects').querySelectorAll('[data-nav-kind=conversation]').length`),1);
    assert.equal(await run('state.conversation'),data.chats[0]);
    await run(`$('navigationSearch').value='';$('navigationSearch').dispatchEvent(new Event('input'));`);checks.push('Search filters folders and chats without altering current context');
    await run(`navigationElement('conversation','${data.chats[2]}').querySelector('.navigation-open').focus();`);await key('F2');
    await run(`navigationUI.editing.input.value='不会保存的改名'`);await key('Escape');assert.equal(await run(`navigationItem('conversation','${data.chats[2]}').title`),'独立论证');checks.push('F2 and Escape support inline keyboard editing');
    // Opening a saved chat remains responsive while a model catalog is slow.
    await run(`window.__navigationApi=api;api=async function(url,options){if(url.startsWith('/api/deepseek/models'))await new Promise(resolve=>setTimeout(resolve,1400));return window.__navigationApi(url,options);};true;`);
    const start=Date.now();await run(`selectConversation('${data.chats[2]}')`);assert.ok(Date.now()-start<1000,'Chat restoration waited for model catalog');
    assert.ok(await run(`$('messages').textContent.includes('第 19 条讨论')`));
    await run('api=window.__navigationApi;true;');await run(`selectConversation('${data.chats[0]}')`);checks.push('Chat restores before a delayed model catalog');
    await run(`api=async function(url,options){if(url.startsWith('/api/projects/${data.other}/')&&/artifacts|exercises|jobs|lesson-feedback/.test(url))await new Promise(resolve=>setTimeout(resolve,1400));return window.__navigationApi(url,options);};true;`);
    const projectStart=Date.now();await run(`openNavigationItem('conversation','${data.foreign}')`);
    assert.ok(Date.now()-projectStart<1000,'Switching project waited for unrelated outcome lists');
    assert.equal(await run(`$('prompt').readOnly`),false);
    await run(`api=window.__navigationApi;true;`);await run(`openNavigationItem('conversation','${data.chats[0]}')`);
    checks.push('Project chat becomes usable before delayed outcome and exercise lists');
    await until('state.sources.length>=40');
    await run(`showView('sources');document.querySelector('[data-preview="${data.source}"]').click();`);await until(`!$('preview-${data.source}').hidden`);
    await run(`showView('study');const source=[...$('quickSources').querySelectorAll('[data-quick-source]')].find(node=>node.dataset.quickSource==='${data.source}');source.scrollIntoView({block:'center'});source.focus();`);
    const scroll=await run(`$('quickSources').scrollTop`);
    await run(`document.querySelector('[data-quick-source="${data.source}"]').click();`);
    assert.equal(await run(`$('quickSources').scrollTop`),scroll);
    assert.equal(await run(`document.activeElement.dataset.quickSource`),data.source);
    assert.equal(await run(`$('preview-${data.source}').hidden`),false);checks.push('Changing selected material keeps focus, scrolling and open preview');
    await context('project',data.other);await choose('delete');await until(`$('navigationDeleteDialog').open`);
    assert.equal(await run('state.project.id'),data.project);
    assert.ok(await run(`$('navigationDeleteImpact').textContent.includes('1 份成果')`));
    await snapshot('删除项目影响说明');await run(`$('confirmNavigationDelete').click()`);await until(`!$('navigationDeleteDialog').open&&!navigationItem('project','${data.other}')`);
    assert.equal(await run(`(async()=>{try{await api('/api/artifacts/${data.artifact}/download');return false;}catch(_){return true;}})()`),true);checks.push('Recycled project is hidden and its old artifact URL is blocked');
    await run(`$('openProjectRecycle').click()`);await until(`!!document.querySelector('[data-restore-project="${data.other}"]')`);await snapshot('项目回收站');
    await run(`document.querySelector('[data-restore-project="${data.other}"]').click()`);await until(`!!navigationItem('project','${data.other}')`);
    await run(`$('closeProjectRecycle').click()`);assert.equal(await run(`(async()=>{const rows=await api('/api/projects/${data.other}/artifacts');return rows.some(row=>row.id==='${data.artifact}');})()`),true);checks.push('Project restore preserves original outcomes and chats');
    await run(`requestNavigationDelete('project','${data.purge}')`);await run(`$('confirmNavigationDelete').click()`);
    await until(`!$('navigationDeleteDialog').open&&!navigationItem('project','${data.purge}')`);
    await run('openProjectRecycle()');await run(`document.querySelector('[data-purge-project="${data.purge}"]').click()`);
    await until(`$('projectPurgeDialog').open`);
    assert.equal(await run(`$('confirmProjectPurge').disabled`),true);
    assert.ok(await run(`$('projectPurgeImpact').textContent.includes('2 份资料')`));
    await run(`$('projectPurgeName').value='错误名称';$('projectPurgeName').dispatchEvent(new Event('input'));`);
    assert.equal(await run(`$('confirmProjectPurge').disabled`),true);
    await run(`$('cancelProjectPurge').click()`);assert.ok(fs.existsSync(data.owned));
    await run(`document.querySelector('[data-purge-project="${data.purge}"]').click()`);await until(`$('projectPurgeDialog').open`);
    await run(`$('projectPurgeName').value=${JSON.stringify(data.purge_name)};$('projectPurgeName').dispatchEvent(new Event('input'));`);
    assert.equal(await run(`$('confirmProjectPurge').disabled`),false);await snapshot('回收站彻底删除确认');
    await run(`$('confirmProjectPurge').click()`);await until(`!$('projectPurgeDialog').open&&!document.querySelector('[data-purge-project="${data.purge}"]')`);
    assert.equal(fs.existsSync(data.owned),false);assert.equal(fs.existsSync(data.external),true);
    assert.equal(await run(`(async()=>{try{await api('/api/projects/${data.purge}/restore',{method:'POST'});return false;}catch(_){return true;}})()`),true);
    await run(`$('closeProjectRecycle').click()`);checks.push('Permanent removal requires the exact name, supports cancel, deletes owned files, preserves external originals and cannot restore');
    await run(`showView('profile')`);await until(`document.querySelector('[data-profile-topic="高斯定律"]')`);
    await run(`$('ratingTopic').value='高斯定律';$('ratingValue').value='100';$('saveRating').click()`);
    await until(`document.querySelector('[data-profile-topic="高斯定律"] .profile-combined-score').textContent.includes('68.0')`);
    await run(`$('profileSelfWeight').value='40';$('profileSelfWeight').dispatchEvent(new Event('input',{bubbles:true}));$('saveProfileScoring').click()`);
    await until(`document.querySelector('[data-profile-topic="高斯定律"] .profile-combined-score').textContent.includes('76.0')&&!$('saveProfileScoring').disabled`);
    const rating=(await run('api("/api/profile")')).find(row=>row.topic==='高斯定律');assert.equal(rating.score,60);assert.equal(rating.learning_score,76);
    assert.ok((await run('api("/__navigation_test__/teaching-context")')).context.includes('综合学习参考分 76/100'));
    await snapshot('自评进入综合学习参考分');checks.push('Self rating affects the actual composite and teaching context; changing weight immediately recomputes scores without changing measured grades');
    await run(`showView('study')`);
    await run(`openNavigationItem('conversation','${data.empty}')`);await context('conversation',data.empty);await choose('delete');await until(`$('navigationDeleteDialog').open`);await run(`$('confirmNavigationDelete').click()`);
    await until(`!state.conversation&&!$('navigationDeleteDialog').open&&!$('confirmNavigationDelete').disabled&&!navigationItem('conversation','${data.empty}')`);
    assert.equal((await rows(data.temporary)).length,0);assert.equal(await run(`$('sendMessage').disabled`),true);assert.equal(await run(`$('newConversation').disabled`),false);checks.push('Deleting last chat leaves an empty project, without creating a replacement chat');
    await run(`openNavigationItem('conversation','${data.chats[0]}');`);
    await run(`expandNavigation('${data.other}',false);expandNavigation('${data.temporary}',false);$('prompt').value='重启后保留的学习问题';$('prompt').dispatchEvent(new Event('input'));`);
    await run(`(async()=>{await flushConversation();await navigationSave;})()`);
    assert.equal(await run('state.conversation'),data.chats[0]);await snapshot('项目与对话文件夹树');
    await run(`expandNavigation('${data.project}',false)`);await run('navigationSave');
    fs.writeFileSync(path.join(root,'expected.json'),JSON.stringify({order:await viewRows(data.project),expanded:await run('[...navigationUI.expanded]'),chat:data.chats[0]}));
  }else{
    const expected=JSON.parse(fs.readFileSync(path.join(root,'expected.json'),'utf8'));
    assert.equal(await run('state.project.id'),data.project);assert.equal(await run('state.conversation'),expected.chat);
    assert.equal(await run(`$('prompt').value`),'重启后保留的学习问题');
    assert.equal(await run(`$('projectTitle').textContent`),'数学 · 证明与构造');
    assert.equal(await run(`$('conversationTitle').textContent`),'如何想到这个证明');
    assert.deepEqual(await viewRows(data.project),expected.order);
    assert.deepEqual((await run('[...navigationUI.expanded]')).sort(),expected.expanded.sort());
    assert.equal(await run(`navigationElement('project','${data.project}').getAttribute('aria-expanded')`),'false');
    assert.equal(await run(`navigationItem('conversation','${data.chats[1]}').pinned`),1);
    assert.equal((await rows(data.temporary)).length,0);
    assert.deepEqual(await run('[...state.selected]'),[]);
    await run(`showView('profile')`);await until(`document.querySelector('[data-profile-topic="高斯定律"]')`);
    assert.equal(await run(`$('profileSelfWeight').value`),'40');
    assert.ok(await run(`document.querySelector('[data-profile-topic="高斯定律"] .profile-combined-score').textContent.includes('76.0')`));
    assert.equal(fs.existsSync(data.owned),false);assert.equal(fs.existsSync(data.external),true);
    assert.equal((await run('api("/api/recycle-bin/projects")')).some(row=>row.id===data.purge),false);
    await run(`showView('study')`);checks.push('Backend restart retains self-rating weights and scores; permanently removed project and files stay removed');
    await snapshot('重启后保留当前项目折叠');await run(`expandNavigation('${data.project}',true)`);await run('navigationSave');
    await snapshot('重启后的稳定导航');checks.push('Actual backend restart with a new port preserves titles, draft, selection, pins, order, current-folder collapse and empty project');
    win.setSize(1120,840);await pause(200);await snapshot('窄屏项目与对话');
    assert.ok(await run('document.documentElement.scrollWidth<=innerWidth'),'Narrow viewport overflow');checks.push('1120px viewport has no horizontal overflow');
  }
  assert.equal((await run('api("/__navigation_test__/state")')).model_calls,0,'Navigation invoked AI inference');
  assert.deepEqual(errors,[],'Browser console errors');
  const reportPath=path.join(root,'result.json'),report=fs.existsSync(reportPath)?JSON.parse(fs.readFileSync(reportPath,'utf8')):{checks:[]};
  report.checks.push(...checks);report['phase'+data.phase]={passed:true,model_calls:0,console_errors:errors};fs.writeFileSync(reportPath,JSON.stringify(report,null,2));
  app.exit(0);
}).catch(error=>{fs.writeFileSync(path.join(root,'failure.json'),JSON.stringify({message:error.stack,errors},null,2));process.stderr.write(error.stack+'\n');app.exit(1);});
