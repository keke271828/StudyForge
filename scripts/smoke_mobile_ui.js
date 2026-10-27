/* Actual Electron render + real LAN-gateway endpoints, isolated fixture only. */
const {app,BrowserWindow,ipcMain,dialog}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const {registerMobileHandlers}=require('../desktop/mobile');
const {diagnose}=require('../desktop/mobile_diagnostics');
const caseFile=process.env.STUDYFORGE_MOBILE_CASE,root=path.dirname(caseFile),data=JSON.parse(fs.readFileSync(caseFile,'utf8'));
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let pc,phone;const errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function execute(win,code){
  let timer;
  try{return await Promise.race([win.webContents.executeJavaScript(code),
    new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Renderer request stalled: '+code)),15000);})]);}
  catch(error){throw new Error('Renderer check failed ['+code.slice(0,400)+']: '+error.message);}
  finally{clearTimeout(timer);}
}
async function until(win,code){for(let i=0;i<280;i++){if(await execute(win,code))return;await sleep(100);}throw new Error('Timeout '+code);}
async function screenshot(win,name){await sleep(200);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function browserDownload(win,clickCode,name){
  const destination=path.join(root,name);
  const saved=new Promise((resolve,reject)=>{
    let activeItem;
    const handler=(_event,item)=>{
      activeItem=item;
      console.log('Download started: '+name+' · '+item.getState()+' · '+item.getTotalBytes());
      item.once('done',(_event,status)=>{
        clearTimeout(timer);activeItem=null;console.log('Download finished: '+name+' · '+status);
        status==='completed'?resolve(item.getFilename()):reject(new Error(status));
      });
      item.setSavePath(destination);
      console.log('Download destination set: '+name+' · '+item.getState());
      if(item.getState()==='completed'){clearTimeout(timer);resolve(item.getFilename());}
    };
    const timer=setTimeout(()=>{
      win.webContents.session.removeListener('will-download',handler);
      const status=activeItem?activeItem.getState()+' · '+activeItem.getReceivedBytes()+'/'+activeItem.getTotalBytes():'not started';
      console.log('Download timeout: '+name+' · '+status);
      reject(new Error('Browser download timed out: '+name+' · '+status));if(activeItem)activeItem.cancel();
    },30000);
    win.webContents.session.once('will-download',handler);
  });
  await execute(win,clickCode);const filename=await saved;
  assert.ok(filename.endsWith('.docx')&&!/^[a-f0-9]{32}/.test(filename));assert.ok(fs.statSync(destination).size>1000);
  return filename;
}
const request=(route,method='GET',value)=>fetch(data.desktop_url+route,{method,headers:{'Content-Type':'application/json','X-StudyForge-Desktop-Token':data.token},body:value===undefined?undefined:JSON.stringify(value)});
app.whenReady().then(async()=>{
  try{
    pc=new BrowserWindow({show:false,width:1320,height:920,webPreferences:{preload:path.resolve('desktop/preload.js'),contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});
    registerMobileHandlers(ipcMain,data.desktop_url,()=>pc,request,dialog);
    // This fixture intentionally uses loopback instead of a real LAN adapter.
    ipcMain.removeHandler('studyforge:mobile-status');
    let fixtureAddress='127.0.0.1',fixtureLegacy=false,quitRequests=0;
    function fixtureInterfaces(status){return [{name:'隔离测试连接',address:fixtureAddress,netmask:'255.0.0.0'},
      ...(status.tailscale?.connected?(status.tailscale.addresses||[]).map(address=>({name:'Tailscale · 固定私人地址',address,netmask:'255.255.255.255',kind:'tailscale'})):[])];}
    ipcMain.handle('studyforge:mobile-status',async()=>{const status=await (await request('/api/mobile/status')).json();return {...status,...(fixtureLegacy?{gateway_version:1}:{}),interfaces:fixtureInterfaces(status)};});
    ipcMain.handle('studyforge:quit',()=>{quitRequests++;return true;});
    ipcMain.removeHandler('studyforge:mobile-start');
    ipcMain.handle('studyforge:mobile-start',async(_event,value)=>{
      // Keep the isolated loopback entry; the backend still verifies and adds
      // the installed client's real private address when requested.
      const response=await request('/api/mobile/start','POST',{...value,addresses:['127.0.0.1']});
      const result=await response.json();if(!response.ok)throw new Error(result.detail);return result;
    });
    ipcMain.removeHandler('studyforge:mobile-diagnostics');
    ipcMain.handle('studyforge:mobile-diagnostics',async(_event,value)=>{
      const status=await (await request('/api/mobile/status')).json(),certificate=await (await request('/api/mobile/certificate')).json();
      return diagnose({status,certificate,interfaces:fixtureInterfaces(status),address:value.address,phoneIP:value.phone_ip});
    });
    for(const [channel,value] of [['desktop-status',{tray_available:true}],['window-state',{fullscreen:false}],['update-status',{state:'idle'}],['notification-status',{supported:false}]])ipcMain.handle('studyforge:'+channel,()=>value);
    ipcMain.handle('studyforge:copy-text',()=>true);
    await pc.loadURL(data.desktop_url);await until(pc,'state.ready && state.conversation && !conversationUI.restoring');
    assert.equal(await execute(pc,'state.conversation'),data.conversation_id);
    await execute(pc,"$('connectMobile').click()");await until(pc,"$('mobilePairingCode').textContent.length===8");
    assert.ok(await execute(pc,"$('mobileConnectionURL').textContent.startsWith('https://')"));
    fixtureLegacy=true;
    await execute(pc,"$('closeMobileConnection').click();$('connectMobile').click()");
    await until(pc,"!$('mobileRuntimeUpdate').hidden && $('setupMobileTailscale').disabled");
    assert.equal(await execute(pc,"$('mobileConnectionQR').hasAttribute('src')"),false);
    assert.equal(await execute(pc,"$('mobileConnectionURL').textContent"),'');
    await execute(pc,"$('exitOldMobileRuntime').click()");await sleep(100);assert.equal(quitRequests,1);
    fixtureLegacy=false;
    await execute(pc,"$('closeMobileConnection').click();$('connectMobile').click()");
    await until(pc,"$('mobileRuntimeUpdate').hidden && !$('setupMobileTailscale').disabled && $('mobileConnectionQR').hasAttribute('src')");
    await execute(pc,"$('diagnoseMobileConnection').click()");
    await until(pc,"$('mobileDiagnosticResult').textContent.includes('手机首页返回 200')");
    assert.ok(await execute(pc,"$('mobileDiagnosticResult').textContent.includes('尚未验证手机到电脑')"));
    await execute(pc,"$('mobileRememberDays').value='90';$('mobileRememberDays').dispatchEvent(new Event('change')); ");
    await sleep(2700);
    assert.equal(await execute(pc,"$('mobileRememberDays').value"),'90','Polling overwrote an unsaved connection preference');
    await execute(pc,"$('saveMobilePreferences').click()");
    await until(pc,"(async()=> (await window.studyforgeDesktop.mobileStatus()).remember_days===90)()");
    assert.equal((await (await request('/api/mobile/status')).json()).remember_days,90);
    await execute(pc,"$('mobileRememberDays').value='365';$('mobileAutoStart').checked=true;$('mobileRememberDays').dispatchEvent(new Event('change'));$('saveMobilePreferences').click()");
    await until(pc,"(async()=>{const value=await window.studyforgeDesktop.mobileStatus();return value.remember_days===365 && value.auto_start;})()");
    fixtureAddress='127.0.0.2';
    await execute(pc,"$('closeMobileConnection').click();$('connectMobile').click()");
    await until(pc,"$('mobileConnectionURL').textContent.includes('网络已切换')");
    assert.equal(await execute(pc,"$('mobileConnectionQR').hasAttribute('src')"),false,'A stale QR remained after changing networks');
    fixtureAddress='127.0.0.1';await execute(pc,"$('closeMobileConnection').click();$('connectMobile').click()");
    await until(pc,"$('mobileConnectionURL').textContent.startsWith('https://') && $('mobileConnectionQR').hasAttribute('src')");
    const networkStatus=await (await request('/api/mobile/status')).json();
    if(networkStatus.tailscale?.connected){
      await execute(pc,"$('setupMobileTailscale').click()");
      await until(pc,"(async()=>{const value=await window.studyforgeDesktop.mobileStatus();return value.enable_tailscale && value.preferred_address && $('mobileConnectionURL').textContent.includes(value.preferred_address);})()");
      const enabled=await (await request('/api/mobile/status')).json();
      assert.equal(enabled.auto_start,true);assert.equal(enabled.remember_days,365);
      data.pairing_code=enabled.pairing_code;
      await execute(pc,"$('diagnoseMobileConnection').click()");
      await until(pc,"$('mobileDiagnosticResult').textContent.includes('固定私人连接') && $('mobileDiagnosticResult').textContent.includes('手机首页返回 200')");
      assert.ok(await execute(pc,"!$('mobileDiagnosticResult').textContent.includes('请优先选择 Wi-Fi')"));
      await execute(pc,"$('mobileDiagnosticResult').hidden=true");
      fs.writeFileSync(path.join(root,'private-ui-report.json'),JSON.stringify({passed:true,checks:['button enabled actual fixed address','auto startup and remembered-device settings persisted','trusted HTTPS self-check through real private address']},null,2));
    }
    await screenshot(pc,'desktop-phone-connection');
    phone=new BrowserWindow({show:false,useContentSize:true,width:390,height:844,webPreferences:{contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});
    // Model an Android device with the exported CA installed. Navigation's
    // certificate-error callback alone does not cover DownloadManager requests.
    const rootCA=new X509Certificate(fs.readFileSync(data.certificate));
    phone.webContents.session.setCertificateVerifyProc((request,callback)=>{
      let approved=false;
      try{
        const leaf=new X509Certificate(request.certificate.data);
        approved=request.hostname===new URL(data.mobile_url).hostname &&
          Boolean(leaf.checkIP(request.hostname)) && leaf.verify(rootCA.publicKey);
      }catch{/* Keep Chromium verification for every other certificate. */}
      callback(approved?0:-3);
    });
    phone.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
    await phone.loadURL(data.mobile_url+'/#pair='+data.pairing_code);await until(phone,"typeof mobile!=='undefined' && !$('pairScreen').hidden");
    await execute(phone,"$('pairForm').requestSubmit()");await until(pc,"$('mobileDeviceList').textContent.includes('等待你确认')");
    assert.equal(await execute(phone,"$('learningApp').hidden"),true,'Phone was admitted before PC approval');
    await execute(pc,"$('mobileDeviceList').querySelector('button').click()");await until(phone,'mobile.authenticated && mobile.chat');
    await execute(phone,"openSheet('optionsDialog');$('mobileHomeShortcut').click()");
    assert.ok(await execute(phone,"$('mobileShortcutDialog').open"));
    assert.equal(await execute(phone,"$('mobileShortcutURL').value"),data.mobile_url+'/');
    await execute(phone,"$('mobileShortcutInstall').click()");
    assert.ok(await execute(phone,"$('mobileShortcutHelp').textContent.includes('浏览器')"));
    await execute(phone,"$('mobileShortcutDialog').querySelector('header button').click()");
    assert.equal(await execute(phone,'mobile.chat.id'),data.conversation_id);
    await execute(phone,"$('openMaterials').click()");
    const base64=fs.readFileSync(data.book).toString('base64');
    await execute(phone,`(()=>{const bytes=Uint8Array.from(atob('${base64}'),c=>c.charCodeAt(0));const files=new DataTransfer();files.items.add(new File([bytes],'phone-book.pdf',{type:'application/pdf'}));$('fileInput').files=files.files;$('fileInput').dispatchEvent(new Event('change'));})()`);
    await until(phone,"mobile.sources.some(row=>row.name==='phone-book.pdf') && mobile.uploading===0");
    const original=await execute(phone,"mobile.sources.find(row=>row.name==='phone-book.pdf')");
    assert.equal(original.status,'stored');
    assert.equal(await execute(phone,'mobile.jobs.length'),0,'Phone upload started parsing automatically');
    await execute(phone,"$('sourceList').querySelector('.item-actions button').click()");
    assert.equal(await execute(phone,"$('sourceScopeDialog').open"),true);
    await execute(phone,"$('scopePreviewNumber').value='3';$('scopeLoadPage').click()");
    await until(phone,"$('scopePageText').value.includes('TARGET_PARAGRAPH_3')");
    assert.equal(await execute(phone,"$('scopePages').value"),'3','Preview did not update the unedited page selection');
    assert.equal(await execute(phone,"$('scopePageText').value.includes('PRIVATE_PAGE_1')"),false);
    await screenshot(phone,'phone-scope-picker');
    await execute(phone,"(()=>{const input=$('scopePageText'),start=input.value.indexOf('TARGET_PARAGRAPH_3');input.focus();input.setSelectionRange(start,input.value.trimEnd().length);$('scopeUseSelection').click();$('sourceScopeForm').requestSubmit();})()");
    await until(phone,"mobile.sources.some(row=>row.kind==='.sfscope') && mobile.selected.size===1");
    const selection=await execute(phone,"mobile.sources.find(row=>row.kind==='.sfscope')");
    assert.equal(await execute(phone,"mobile.sources.find(row=>row.name==='phone-book.pdf').status"),'stored');
    assert.equal(await execute(phone,'mobile.jobs.length'),0,'Text selection started a whole-book parser');
    await screenshot(phone,'phone-select-scope');
    await execute(phone,"$('materialsDialog').close();$('prompt').value='请解释我刚才选的原文';$('composer').requestSubmit()");
    await until(phone,'mobile.runs.size===1');
    // Reload while the backend is still working. The request must survive.
    await phone.reload();await until(phone,"mobile.authenticated && $('messages').textContent.includes('正文末尾')");
    assert.deepEqual(await execute(phone,'[...mobile.selected]'),[selection.id],'An idle desktop library refresh erased phone material choices');
    assert.equal(await execute(phone,"$('messages').querySelectorAll('.katex').length>=2"),true);
    const calls=JSON.parse(fs.readFileSync(path.join(root,'requests.json'),'utf8')),chatCall=calls.find(row=>row.messages[0].content.includes('TARGET_PARAGRAPH_3'));
    assert.ok(chatCall,'Tutor never received selected original paragraph');
    assert.equal(chatCall.messages[0].content.includes('PRIVATE_PAGE_1'),false);
    assert.equal(chatCall.messages[0].content.includes('PRIVATE_PAGE_3'),false,'Tutor received the rest of the selected page');
    await screenshot(phone,'phone-learning');
    const before=await execute(phone,"$('messages').clientHeight");await execute(phone,"$('focusMode').click()");
    assert.ok(await execute(phone,"$('messages').clientHeight")>before+65,'Focus mode did not enlarge reading area');
    assert.equal(await execute(phone,"getComputedStyle(document.querySelector('.topbar')).display"),'none');
    assert.equal(await execute(phone,"getComputedStyle(document.querySelector('.workspace-strip')).display"),'none');
    assert.ok(await execute(phone,"$('composer').getBoundingClientRect().bottom<=innerHeight+1"));
    assert.equal(await execute(phone,'document.documentElement.scrollWidth>innerWidth'),false);
    await screenshot(phone,'phone-focus');
    phone.setContentSize(320,640);await sleep(250);assert.equal(await execute(phone,'document.documentElement.scrollWidth>innerWidth'),false);
    await screenshot(phone,'phone-focus-small');phone.setContentSize(390,844);
    await execute(phone,"$('focusExit').click();$('openGenerate').click();$('outputFormat').value='docx';$('generateForm').requestSubmit()");
    await until(phone,"mobile.jobs.some(row=>row.kind==='generate'&&['completed','failed'].includes(row.status))");
    const job=await execute(phone,"mobile.jobs.find(row=>row.kind==='generate')");assert.equal(job.status,'completed',job.error);
    await until(phone,'mobile.artifacts.length>0');
    await execute(phone,"$('openArtifacts').click()");
    const artifact=await execute(phone,"mobile.artifacts.find(row=>row.kind==='explanation')");assert.ok(artifact);
    // Browser download through authenticated HTTPS, not a direct disk shortcut.
    const filename=await browserDownload(phone,"$('artifactList').querySelector('.download-link').click()",'downloaded.docx');
    await screenshot(phone,'phone-artifacts');
    await execute(phone,"$('artifactList').querySelector('button').click()");assert.ok(await execute(phone,`mobile.selected.has('${artifact.source_id||''}') || mobile.sources.some(row=>row.artifact_id==='${artifact.id}'&&mobile.selected.has(row.id))`));
    // Lecture feedback is optional and belongs to the original dialogue. A
    // deliberately slow supplement must survive refresh and chat navigation.
    console.log('Mobile lecture feedback: draft and scoped supplement');
    const selectedBeforeFeedback=await execute(phone,'[...mobile.selected].sort()');
    await execute(phone,"(()=>{for(const [id,value] of [['learningMode','research'],['explanationStyle','academic'],['outputLanguage','en']]){$(id).value=value;$(id).dispatchEvent(new Event('change'));}})()");
    await execute(phone,'mobile.save');
    await execute(phone,"$('openArtifacts').click();$('artifactList').querySelector('[data-lesson-feedback-artifact]').click()");
    await until(phone,"$('lessonFeedbackDialog').open && $('lessonFeedbackChoices').querySelectorAll('input').length===6");
    assert.ok(await execute(phone,"$('lessonFeedbackContext').textContent.includes('原讲解')"));
    await execute(phone,"(()=>{for(const id of ['prerequisites','motivation']){const input=$('lessonFeedbackChoices').querySelector('input[value=\"'+id+'\"]');input.checked=true;input.dispatchEvent(new Event('change'));}$('lessonFeedbackOther').value='请重新说明选段里的条件为什么必要，不要额外出题。';$('lessonFeedbackOther').dispatchEvent(new Event('input'));})()");
    await screenshot(phone,'phone-lesson-feedback');
    await phone.reload();await until(phone,"mobile.authenticated && !$('lessonFeedbackNotice').hidden");
    await execute(phone,"$('lessonFeedbackNoticeOpen').click()");
    await until(phone,"$('lessonFeedbackDialog').open && $('lessonFeedbackOther').value.includes('条件为什么必要')");
    assert.equal(await execute(phone,"$('lessonFeedbackChoices').querySelectorAll('input:checked').length"),2);
    const supplementCalls=()=>JSON.parse(fs.readFileSync(path.join(root,'requests.json'),'utf8')).filter(row=>row.messages[0].content.includes('本次是讲解后补讲'));
    assert.equal(supplementCalls().length,0,'Draft feedback called a model');
    phone.setContentSize(320,640);await execute(phone,"theme('dark')");await sleep(200);
    assert.equal(await execute(phone,'document.documentElement.scrollWidth>innerWidth'),false);
    assert.equal(await execute(phone,"$('lessonFeedbackDialog').scrollWidth>$('lessonFeedbackDialog').clientWidth+1"),false);
    await screenshot(phone,'phone-lesson-feedback-small-dark');phone.setContentSize(390,844);await execute(phone,"theme('light');$('lessonFeedbackForm').requestSubmit()");
    await until(phone,'mobile.runs.size===1');
    assert.equal(await execute(phone,"api('/api/projects/"+data.project_id+"/lesson-feedback').then(rows=>rows[0].status)"),'submitted');
    await phone.reload();await until(phone,"mobile.authenticated && [...mobile.runs.values()].some(row=>row.state?.kind==='lesson_feedback')");
    assert.equal(await execute(phone,"$('learningMode').value"),'research');
    await execute(phone,"selectChat('"+data.second_conversation_id+"')");
    await until(phone,"mobile.chat?.id==='"+data.second_conversation_id+"' && $('lessonFeedbackNotice').hidden");
    assert.equal(await execute(phone,"$('messages').textContent.includes('条件为什么必要')"),false);
    const releasedFeedback=await request('/__mobile_test__/release-feedback','POST');assert.equal(releasedFeedback.status,200);
    await until(phone,'mobile.runs.size===0');
    assert.equal(await execute(phone,"mobile.chat.id"),data.second_conversation_id,'A background supplement changed the active conversation');
    assert.equal(await execute(phone,"$('messages').textContent.includes('PHONE_LESSON_SUPPLEMENT')"),false);
    await execute(phone,"selectChat('"+data.conversation_id+"')");
    await until(phone,"mobile.chat?.id==='"+data.conversation_id+"' && $('messages').textContent.includes('PHONE_LESSON_SUPPLEMENT')");
    assert.deepEqual(await execute(phone,'[...mobile.selected].sort()'),selectedBeforeFeedback,'Supplement changed current materials');
    assert.equal(await execute(phone,"$('learningMode').value"),'research');
    assert.equal(await execute(phone,"$('explanationStyle').value"),'academic');
    assert.equal(await execute(phone,"$('outputLanguage').value"),'en');
    assert.equal(supplementCalls().length,1,'Reload or double handling repeated the supplement request');
    const supplementPrompt=supplementCalls()[0].messages[0].content;
    assert.ok(supplementPrompt.includes('TARGET_PARAGRAPH_3'));
    assert.equal(supplementPrompt.includes('PRIVATE_PAGE_1'),false);
    assert.equal(supplementPrompt.includes('PRIVATE_PAGE_3'),false);
    assert.equal(await execute(phone,"mobile.sources.find(row=>row.name==='phone-book.pdf').status"),'stored');
    assert.equal(await execute(phone,"$('lessonFeedbackNotice').hidden"),true);
    await execute(phone,"studyforgeMobileLessonFeedback.open()");await until(phone,"$('lessonFeedbackList').querySelector('[data-lesson-feedback-id]')");
    await execute(phone,"$('lessonFeedbackList').querySelector('[data-lesson-feedback-id]').click()");
    await until(phone,"$('lessonFeedbackResult').textContent.includes('补讲已写入原对话')");
    await screenshot(phone,'phone-lesson-feedback-completed');await execute(phone,"$('lessonFeedbackDialog').close()");
    // Desktop drag/drop uses the exact same staged import API.
    await execute(pc,"$('closeMobileConnection').click();showView('study')");
    await execute(pc,"(()=>{const transfer=new DataTransfer();transfer.items.add(new File(['PC_UPLOAD_NO_PARSE'],'desktop.txt'));$('composerFiles').files=transfer.files;$('composerFiles').dispatchEvent(new Event('change'));})()");
    await until(pc,"state.sources.some(row=>row.name==='desktop.txt')");
    assert.equal(await execute(pc,"state.sources.find(row=>row.name==='desktop.txt').status"),'stored');
    await screenshot(pc,'desktop-stored-materials');
    // Complete mobile homework: no answer release before full submission,
    // local solutions first, questionnaire before the separate teaching report.
    console.log('Mobile homework: opening answer form');
    await execute(phone,"$('artifactsDialog').close();$('openHomework').click()");
    await until(phone,"$('homeworkList').querySelectorAll('[data-homework-set]').length===2");
    await execute(phone,"$('homeworkList').querySelector('[data-homework-set=\""+data.worksheet_id+"\"]').click()");
    await until(phone,"$('homeworkQuestions').querySelectorAll('textarea').length===2");
    assert.equal(await execute(phone,"api('/api/exercises/"+data.worksheet_id+"').then(row=>'solutions' in row)"),false);
    await execute(phone,"$('homeworkQuestions').querySelector('textarea').value='我不知道变量的意义';$('homeworkComplete').checked=true;$('homeworkAnswerForm').requestSubmit()");
    await sleep(200);
    assert.equal(await execute(phone,"api('/api/projects/"+data.project_id+"/homework').then(rows=>rows.length)"),0,'An incomplete answer unlocked solutions');
    await execute(phone,"(()=>{const files=new DataTransfer();files.items.add(new File(['第1题：不懂变量的意义；第2题：2+3=4'],'student-answers.txt',{type:'text/plain'}));$('homeworkFile').files=files.files;$('homeworkFile').dispatchEvent(new Event('change'));})()");
    const extractionCount=()=>JSON.parse(fs.readFileSync(path.join(root,'requests.json'),'utf8')).filter(row=>row.messages[0].content.includes('从学生作答文件中提取')).length;
    assert.equal(extractionCount(),0,'Selecting an answer file began parsing before the explicit action');
    await execute(phone,"$('homeworkExtract').click()");
    await until(phone,"$('homeworkFileStatus').textContent.includes('尚未提交') && $('homeworkQuestions').querySelectorAll('textarea')[1].value.includes('2+3=4')");
    assert.equal(await execute(phone,"$('homeworkComplete').checked"),false,'New extracted answers did not require confirmation');
    await screenshot(phone,'phone-homework-answers');
    console.log('Mobile homework: submitting full answers');
    await execute(phone,"$('homeworkComplete').checked=true;$('homeworkAnswerForm').requestSubmit()");
    await until(phone,"$('homeworkResult').querySelectorAll('.download-link').length===1 && $('homeworkAnswerForm').hidden");
    console.log('Mobile homework: immediate solution link available');
    const solutionFilename=await browserDownload(phone,"$('homeworkResult').querySelector('.download-link').click()",'homework-solutions.docx');
    assert.equal(await execute(phone,"mobile.artifacts.some(row=>row.kind==='grading')"),false,'A report was released before grading');
    await execute(phone,"$('homeworkDialog').close();$('prompt').value='批改时，我还想继续讨论变量的意义';$('composer').requestSubmit()");
    await until(phone,"mobile.runs.size===1");
    await until(phone,"mobile.runs.size===0 && $('messages').textContent.includes('正文末尾')");
    const release=await request('/__mobile_test__/release-grade','POST');assert.equal(release.status,200);
    console.log('Mobile homework: grading released');
    await until(phone,"!$('homeworkNotice').hidden");
    await execute(phone,"$('homeworkNoticeOpen').click()");
    await until(phone,"!$('homeworkCauses').hidden && $('homeworkCauseQuestions').querySelector('textarea')");
    assert.equal(await execute(phone,"$('homeworkResult').querySelectorAll('.download-link').length"),1,'Unclear cause did not hold the report');
    await execute(phone,"(()=>{const card=$('homeworkCauseQuestions').querySelector('[data-cause-index=\"0\"]');card.querySelector('input[value=\"terminology\"]').checked=true;card.querySelector('textarea').value='我把变量符号当作计算结果，不懂它表示的量';card.querySelector('textarea').dispatchEvent(new Event('input',{bubbles:true}));})()");
    await until(phone,"$('homeworkCauseSave').textContent.includes('已同步')");
    await screenshot(phone,'phone-homework-questionnaire');
    await execute(phone,"$('homeworkDialog').close();selectChat('"+data.second_conversation_id+"')");
    await until(phone,"mobile.chat.id==='"+data.second_conversation_id+"' && $('homeworkNotice').hidden");
    await phone.reload();await until(phone,"mobile.authenticated && mobile.chat?.id==='"+data.second_conversation_id+"'");
    assert.equal(await execute(phone,"$('homeworkNotice').hidden"),true,'Questionnaire appeared in another conversation');
    await execute(phone,"selectChat('"+data.conversation_id+"')");
    await until(phone,"mobile.chat.id==='"+data.conversation_id+"' && !$('homeworkNotice').hidden");
    await execute(phone,"$('homeworkNoticeOpen').click()");
    await until(phone,"$('homeworkCauseQuestions').querySelector('textarea')?.value.includes('变量符号')");
    await execute(phone,"$('homeworkCausesForm').requestSubmit()");
    await until(phone,"$('homeworkResult').querySelectorAll('.download-link').length===2 && $('homeworkCauses').hidden");
    const feedbackFilename=await browserDownload(phone,"$('homeworkResult').querySelectorAll('.download-link')[1].click()",'homework-feedback.docx');
    await screenshot(phone,'phone-homework-feedback');
    console.log('Mobile homework: questionnaire and report passed');
    assert.equal(await execute(phone,"api('/api/exercises/"+data.worksheet_id+"/submissions').then(rows=>rows.length)"),1,'Questionnaire resume regraded the submission');
    await until(phone,"!$('homeworkFeynman').hidden");
    await execute(phone,"$('homeworkFeynmanText').value='变量符号表示一个指定的量，要先解释每个量再计算。';$('homeworkFeynmanText').dispatchEvent(new Event('input',{bubbles:true}));$('homeworkFeynmanForm').requestSubmit()");
    await until(phone,"mobile.jobs.some(row=>row.kind==='feynman'&&row.status==='completed')");
    await until(phone,"$('homeworkFeynmanFeedback').textContent.includes('75/100')");
    assert.equal(await execute(phone,"$('homeworkFeynman').hidden"),false,'An unsuccessful Feynman response removed the retry entrance');
    // Non-Python assignment, explicit UTF-16 code preview, provisional static feedback.
    await execute(phone,"studyforgeMobileHomework.openSet('"+data.program_id+"')");
    await until(phone,"$('homeworkDescription').textContent.includes('JavaScript')");
    assert.equal(await execute(phone,"$('homeworkFile').accept"),'.js');
    const codeBytes=fs.readFileSync(data.code_file).toString('base64');
    await execute(phone,"(()=>{const files=new DataTransfer();files.items.add(new File([Uint8Array.from(atob('"+codeBytes+"'),c=>c.charCodeAt(0))],'answer.js'));$('homeworkFile').files=files.files;$('homeworkFile').dispatchEvent(new Event('change'));})()");
    assert.equal(await execute(phone,"$('homeworkQuestions').querySelector('textarea').value"),'');
    await execute(phone,"$('homeworkExtract').click()");
    await until(phone,"$('homeworkQuestions').querySelector('textarea').value.includes('中文代码说明')");
    await execute(phone,"$('homeworkComplete').checked=true;$('homeworkAnswerForm').requestSubmit()");
    await until(phone,"$('homeworkResult').querySelectorAll('.download-link').length===2");
    assert.ok(await execute(phone,"$('homeworkResult').textContent.includes('没有最终分数')"));
    const codeFeedbackFilename=await browserDownload(phone,"$('homeworkResult').querySelectorAll('.download-link')[1].click()",'coding-feedback.docx');
    await screenshot(phone,'phone-coding-feedback');
    await execute(phone,"$('homeworkDialog').close()");
    // Switching projects must not mix artifacts or selected sources.
    await execute(phone,`$('openWorkspace').click();$('projectSelect').value='${data.other_project_id}';$('projectSelect').dispatchEvent(new Event('change'))`);
    await until(phone,`mobile.project.id==='${data.other_project_id}' && mobile.artifacts.length===0`);
    assert.equal(await execute(phone,'mobile.selected.size'),0);
    assert.equal(await execute(phone,"$('homeworkCount').textContent"),'0');
    assert.equal(await execute(phone,"$('homeworkNotice').hidden"),true);
    assert.equal(await execute(phone,"$('lessonFeedbackNotice').hidden"),true);
    assert.equal(await execute(phone,"$('lessonFeedbackList').children.length"),1);
    assert.deepEqual(errors.filter(message=>!message.includes('401')&&!message.includes('ERR_CERT')),[]);
    fs.writeFileSync(path.join(root,'ui-report.json'),JSON.stringify({passed:true,checks:['PC-confirmed pairing','stored PC and phone uploads','single-page preview','exact-text scope','only chosen paragraph sent to tutor','reply survives reload','Markdown and equations','focus enlarges reading area','320px no overflow','DOCX generation and browser download','reuse project artifact','six optional understanding difficulties','lecture feedback draft survives reload without AI calls','320px dark questionnaire without overflow','supplement survives reload','supplement isolated by conversation','only selected original paragraph in supplement','supplement preserves later materials and teaching options','single supplement request and completed feedback recovery','private answers before full submission','explicit answer-file recognition','immediate solutions without waiting for grader','chat while grading','questionnaire gates report','questionnaire draft survives reload','questionnaire isolated by conversation','resume without duplicate grade','Feynman retry with feedback','JavaScript UTF-16 preview','static review without fake final score','project isolation'],download_filename:filename,homework_downloads:[solutionFilename,feedbackFilename,codeFeedbackFilename]},null,2));
    console.log('MOBILE_UI_PASS '+root);app.exit(0);
  }catch(error){console.error(error.stack);fs.writeFileSync(path.join(root,'ui-errors.json'),JSON.stringify({error:String(error.stack),console:errors},null,2));if(phone)await screenshot(phone,'phone-failure');if(pc)await screenshot(pc,'desktop-failure');app.exit(1);}
});
