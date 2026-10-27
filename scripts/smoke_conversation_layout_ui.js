const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_DISPLAY_CASE,'utf8')),root=path.dirname(process.env.STUDYFORGE_DISPLAY_CASE);
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=async code=>{try{return await win.webContents.executeJavaScript(code,true);}catch(error){throw Error(error.message+'\nCode: '+code+'\nRenderer: '+JSON.stringify(errors));}};
async function until(code){for(let n=0;n<160;n++){if(await run(`Boolean(${code})`))return;await sleep(50);}throw Error('Timeout: '+code);}
async function geometry(){return run(`(()=>{const m=$('messages').getBoundingClientRect(),c=document.querySelector('.composer').getBoundingClientRect(),g=readingGeometry();return {reading:m.height,composer:c.height,minimum:g.minimum,share:studioPreferences.ui_reading_share,children:[...g.composer.children].map(el=>[el.id||el.className,el.getBoundingClientRect().height,getComputedStyle(el).marginTop,getComputedStyle(el).marginBottom]),viewport:innerHeight,send:$('sendMessage').getBoundingClientRect().bottom,generate:$('generate').getBoundingClientRect().bottom,horizontal:document.documentElement.scrollWidth-innerWidth};})()`);}
async function drag(delta){const point=await run(`(()=>{const r=$('readingResizeHandle').getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`);
  win.webContents.sendInputEvent({type:'mouseDown',...point,button:'left',clickCount:1});
  for(let n=1;n<=10;n++){win.webContents.sendInputEvent({type:'mouseMove',x:point.x,y:Math.max(20,Math.min((await geometry()).viewport-30,point.y+Math.round(delta*n/10))),button:'left'});await sleep(20);}
  win.webContents.sendInputEvent({type:'mouseUp',x:point.x,y:Math.max(20,Math.min((await geometry()).viewport-30,point.y+delta)),button:'left',clickCount:1});await sleep(400);await run('flushStudioDraft()');await run('studioSave');await sleep(100);
}
app.whenReady().then(async()=>{
  try{
    win=new BrowserWindow({show:false,width:1480,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
    win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
    await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring&&conversationLayoutReady');await sleep(200);
    await run(`$('prompt').value='保留草稿和格式';window.originalMessage=$('messages').querySelector('.message.assistant');window.originalFormat=$('outputFormat').value`);
    const normal=await geometry();await run(`$('toggleGenerationOptions').click()`);await until(`!studioPending`);await sleep(150);
    const collapsed=await geometry();assert.ok(collapsed.reading>normal.reading+30,JSON.stringify({normal,collapsed}));assert.equal(await run(`getComputedStyle($('outputFormat').closest('.control')).display`),'none');
    await drag(-120);const inputLarger=await geometry();assert.ok(inputLarger.composer>collapsed.composer+75,JSON.stringify({collapsed,inputLarger}));
    await drag(380);const readingLarger=await geometry();assert.ok(readingLarger.reading>inputLarger.reading+100,JSON.stringify({readingLarger,inputLarger}));
    await run(`$('expandConversation').click();$('readingResizeHandle').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))`);await until('!studioPending');await sleep(180);
    const maximum=await geometry();assert.ok(maximum.reading>maximum.viewport*.65,JSON.stringify(maximum));assert.ok(maximum.send<=maximum.viewport&&maximum.generate<=maximum.viewport&&maximum.horizontal<=1);
    assert.equal(await run(`$('prompt').value==='保留草稿和格式'&&$('outputFormat').value===window.originalFormat&&window.originalMessage===$('messages').querySelector('.message.assistant')`),true);
    fs.writeFileSync(path.join(root,'最大阅读区.png'),(await win.webContents.capturePage()).toPNG());
    await run(`restoreConversationLayout()`);await sleep(120);const beforeReload=await geometry();await win.reload();await until('state.ready&&!conversationUI.restoring');await sleep(180);
    assert.equal(await run('studioPreferences.ui_generation_options_visible'),false);assert.equal(await run('studioPreferences.ui_reading_share'),.95);
    const afterReload=await geometry();assert.ok(Math.abs(beforeReload.reading-afterReload.reading)<4,JSON.stringify({beforeReload,afterReload}));
    await run(`$('toggleGenerationOptions').click()`);await until('!studioPending');assert.equal(await run(`getComputedStyle($('outputFormat').closest('.control')).display`)!=='none',true);
    win.setSize(1080,700);await sleep(150);await run(`$('expandConversation').click();$('readingResizeHandle').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))`);await until('!studioPending');await sleep(180);
    const small=await geometry();assert.ok(small.reading>200&&small.send<=small.viewport&&small.generate<=small.viewport&&small.horizontal<=1,JSON.stringify(small));
    assert.equal((await run(`api('/__display_test__/state')`)).model_calls,0);assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({passed:true,normal,collapsed,inputLarger,readingLarger,maximum,small,native_drag_works:true,draft_and_document_options_preserved:true,reload_restores:true,model_calls:0,errors},null,2));win.destroy();app.exit(0);
  }catch(error){fs.writeFileSync(path.join(root,'failure.txt'),error.stack+'\n'+JSON.stringify(errors));console.error(error);app.exit(1);}
});
