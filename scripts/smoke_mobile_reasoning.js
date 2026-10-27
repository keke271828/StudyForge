const {app,BrowserWindow}=require('electron'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.resolve(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'model-browser'));app.disableHardwareAcceleration();
const checks=[],errors=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,c)=>w.webContents.executeJavaScript(c);
let pc,phone;
async function until(w,c){for(let i=0;i<200;i++){if(await run(w,c))return;await sleep(100);}throw new Error('Timeout '+c);}
const desktop=(route,method='GET',value)=>`fetch(${JSON.stringify(route)},{method:'${method}',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:${value===undefined?'undefined':JSON.stringify(JSON.stringify(value))}}).then(async r=>{if(!r.ok)throw new Error(await r.text());return r.json()})`;
app.whenReady().then(async()=>{
 try{
  pc=new BrowserWindow({show:false,width:1440,height:950,webPreferences:{preload:path.resolve('desktop/preload.js'),sandbox:true,contextIsolation:true,backgroundThrottling:false}});
  phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
  for(const win of [pc,phone])win.webContents.on('console-message',e=>{if(e.level==='error')errors.push(e.message);});
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&Boolean(state.conversation)");
  const pair=await run(pc,desktop('/api/mobile/pairing','POST'));
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,"$('deviceName').value='推理参数验收手机';$('pairForm').requestSubmit()");
  await until(pc,desktop('/api/mobile/status')+".then(s=>s.devices.some(x=>x.status==='pending'))");
  const device=await run(pc,desktop('/api/mobile/status')+".then(s=>s.devices.find(x=>x.status==='pending'))");
  await run(pc,desktop('/api/mobile/devices/'+device.id+'/approve','POST',{approved:true}));
  await until(phone,"mobile.authenticated&&mobile.chat?.id==='"+data.conversation_id+"'&&mobile.catalog.length>0");
  assert.deepEqual(await run(phone,"({hidden:$('effortField').hidden,disabled:$('effort').disabled,value:$('effort').value,values:[...$('effort').options].map(x=>x.value)})"),{hidden:false,disabled:false,value:'high',values:['','none','low','high','max']});
  checks.push('Saved DeepSeek effort is visible and restored with the same choices as desktop');
  await run(phone,"$('optionsDialog').showModal()");fs.writeFileSync(path.join(folder,'phone-reasoning.png'),(await phone.webContents.capturePage()).toPNG());await run(phone,"$('optionsDialog').close();$('useMaterials').checked=false");
  for(const effort of ['low','high','none','max']){
   const before=await run(pc,desktop('/__library_test__/calls')+'.then(x=>x.calls.length)');
   await run(phone,`$('effort').value='${effort}';$('effort').dispatchEvent(new Event('change'));$('prompt').value='EFFORT_${effort}：为什么需要明确公式的条件？';send()`);
   await until(pc,desktop('/__library_test__/calls')+`.then(x=>x.calls.length>${before})`);
   await until(phone,"!mobile.sending?.size&&![...mobile.runs.values()].some(x=>['queued','running'].includes(x.status))");
   const body=await run(pc,desktop('/__library_test__/calls')+'.then(x=>x.calls.at(-1))');
   assert.equal(body.model,'deepseek-flash');assert.equal(body.thinking.type,effort==='none'?'disabled':'enabled');
   if(effort!=='none')assert.equal(body.reasoning_effort,effort);else assert.equal(body.reasoning_effort,undefined);
  }
  checks.push('Low/high/off/max selections actually change all four DeepSeek chat request bodies');
  await run(phone,"$('model').value='';renderEfforts();$('effort').value='high';$('effort').dispatchEvent(new Event('change'));saveChanges({model:null,model_choice:''})");
  assert.equal(await run(phone,"$('effort').disabled"),false);checks.push('Blank model uses the service default without disabling reasoning');
  await run(phone,`window._generationRequest=null;var actualModelAPI=api;api=async(url,options)=>{if(url==='/api/generate')window._generationRequest=JSON.parse(options.body);return actualModelAPI(url,options);};mobile.selected=new Set(['${data.source_id}']);saveChanges({source_ids:[...mobile.selected]});$('reviewMode').value='express';$('generationInstructions').value='';$('outputFormat').value='docx';$('withExercises').checked=false;$('generationContent').value='explanation';$('generateDialog').showModal();$('generateForm').requestSubmit()`);
  await until(pc,desktop(`/api/projects/${data.project_id}/jobs`)+".then(x=>x.some(j=>j.kind==='generate'&&j.status==='completed'))");
  const request=await run(phone,'window._generationRequest');
  assert.equal(request.reasoning_effort,'high');assert.equal(request.mentor_reasoning_effort,'high');
  const records=await run(pc,desktop('/__library_test__/calls')+'.then(x=>x.calls)');
  assert(records.filter(x=>!x.messages.at(-1).content.includes('EFFORT_')).every(x=>x.reasoning_effort==='high'));
  checks.push('Phone generation completes a real DOCX task with high effort in its frozen mentor and writer settings');
  await run(phone,"$('newConversation').click()");await until(phone,"mobile.chat?.id!=='"+data.conversation_id+"'&&mobile.catalog.length>0");
  assert.equal(await run(phone,"mobile.chat.reasoning_effort"),'high');checks.push('A new DeepSeek conversation inherits the selected reasoning strength');
  const created=await run(phone,"mobile.chat.id");await phone.reload();await until(phone,`mobile.authenticated&&mobile.chat?.id==='${created}'&&mobile.catalog.length>0`);assert.equal(await run(phone,"$('effort').value"),'high');
  checks.push('The selected strength survives phone page reload and pairing reuse');
  await run(phone,"$('provider').value='codex';$('provider').dispatchEvent(new Event('change'))");await until(phone,"mobile.catalog.some(x=>x.id==='gpt-fixture-wide')");
  await run(phone,"$('model').value='gpt-fixture-wide';$('model').dispatchEvent(new Event('change'));$('effort').value='max';$('effort').dispatchEvent(new Event('change'));$('model').value='gpt-fixture-narrow';$('model').dispatchEvent(new Event('change'))");
  assert.equal(await run(phone,"selectedReasoning()"),null);assert.deepEqual(await run(phone,"[...$('effort').options].map(x=>x.value)"),['','low']);
  checks.push('Switching Codex to a model without max clears the incompatible choice instead of silently sending it');
  await run(phone,`$('provider').value='${data.custom_provider}';$('provider').dispatchEvent(new Event('change'))`);await until(phone,"mobile.catalog.length>0&&$('effortField').hidden");assert.equal(await run(phone,"requestSnapshot().reasoning_effort"),null);
  checks.push('A third party without configured reasoning capability receives no unsupported parameter');
  assert.equal(errors.length,0);fs.writeFileSync(path.join(folder,'reasoning-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,requests:records.map(x=>({model:x.model,effort:x.reasoning_effort||null,thinking:x.thinking}))},null,2));
  phone.destroy();pc.destroy();app.quit();
 }catch(error){fs.writeFileSync(path.join(folder,'reasoning-ui-report.json'),JSON.stringify({passed:false,error:String(error.stack||error),checks,console_errors:errors},null,2));phone?.destroy();pc?.destroy();app.exit(1);}
});
