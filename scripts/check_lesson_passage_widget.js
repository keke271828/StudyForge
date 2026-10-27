/* Actual renderer checks for native Enter behaviour and exact selection. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const folder=path.resolve(process.argv[2]),errors=[],checks=[];
const sample='😀起点\r\n这里是选中原句\r\n仍属于选中段。后面的上下文',excerpt='这里是选中原句\r\n仍属于选中段。';
app.setPath('userData',path.join(folder,'widget-electron'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:800,height:700,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}});
 const run=code=>w.webContents.executeJavaScript(code),sleep=ms=>new Promise(r=>setTimeout(r,ms));
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 try{
  const source=fs.readFileSync(path.join(__dirname,'../web/lesson_passage.js'),'utf8');
  await w.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent('<form id="form"><div id="host"></div><button>Submit</button></form><script>'+source+'</script>'));
  await run(`window.submits=0;document.getElementById('form').onsubmit=e=>{e.preventDefault();submits++};
    window.calls=[];window.raw=${JSON.stringify(sample)};window.section='s';
    window.control=studyforgeLessonPassage.create(document.getElementById('host'),{getId:()=> 'q',getSection:()=>section,onChange:()=>{},api:async url=>{const offset=Number(new URL(url,'http://local').searchParams.get('offset'));calls.push(offset);return {offset,end:Array.from(raw).length,total:Array.from(raw).length,text:Array.from(raw).slice(offset).join(''),previous_offset:offset?0:null,next_offset:null};}});control.setSection(section);document.querySelector('[data-passage-open]').click();`);
  await sleep(50);
  const chosen=await run(`(()=>{const t=document.querySelector('[data-passage-text]'),start=t.value.indexOf('这里'),end=t.value.indexOf('后面');t.setSelectionRange(start,end);document.querySelector('[data-passage-use]').click();return control.value()})()`);
  const expected={text:excerpt,start:5,end:5+Array.from(excerpt).length};
  assert.deepEqual(chosen,expected);checks.push('Native textarea maps emoji and normalized CRLF selection back to the exact saved Unicode coordinates');
  await run("const p=document.querySelector('[data-passage-offset]');p.value='2';p.focus()");
  w.webContents.sendInputEvent({type:'keyDown',keyCode:'Enter'});w.webContents.sendInputEvent({type:'keyUp',keyCode:'Enter'});await sleep(100);
  assert.equal(await run('submits'),0);assert.deepEqual(await run('calls'),[0,1]);checks.push('Native Enter in the position input jumps to the passage and never submits the feedback form');
  await run("document.querySelector('[data-passage-clear]').click()");assert.equal(await run('control.value()'),null);
  await run("section='new';control.setSection(section)");assert(await run("document.querySelector('[data-passage-reader]').hidden"));checks.push('Cancel and section changes clear only the optional quote without submitting feedback');
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'widget-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,external_model_requests:0},null,2));w.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'widget-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));w.destroy();app.exit(1);}
});
