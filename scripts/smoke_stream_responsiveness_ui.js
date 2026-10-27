/* Exercise actual Markdown/math rendering with a fast offline response stream. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_DISPLAY_CASE,'utf8')),root=path.dirname(process.env.STUDYFORGE_DISPLAY_CASE);
app.setPath('userData',path.join(root,'stream-profile'));app.disableHardwareAcceleration();
app.on('window-all-closed',()=>{});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));let win;const errors=[];
app.whenReady().then(async()=>{
  try{
    win=new BrowserWindow({show:false,width:1480,height:960,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
    win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
    await win.loadURL(input.url);
    for(let n=0;n<160;n++){if(await win.webContents.executeJavaScript('state.ready&&state.conversation&&!conversationUI.restoring'))break;if(n===159)throw Error('UI startup timeout');await sleep(50);}
    const result=await win.webContents.executeJavaScript(`(async()=>{
      const request={project_id:state.project.id,conversation_id:state.conversation};
      const original=renderLessonText;let renders=0,ticks=0;
      renderLessonText=(target,text)=>{renders++;original(target,text);};
      const tick=setInterval(()=>ticks++,20);
      const content='# 连续回复测试\\n\\n'+Array.from({length:30},(_,i)=>'## 步骤 '+i+'\\n\\n具体对象、成立条件与方法动机。$F=ma$。\\n\\n> 原文引句保持字体与颜色。\\n\\n').join('')+'<script>window.badStreamScript=true</script>\\n';
      const pieces=Array.from({length:Math.ceil(content.length/8)},(_,i)=>content.slice(i*8,(i+1)*8));
      const output=message('assistant','');const live={request,output,answer:'',finished:false};
      const encoder=new TextEncoder();
      const stream=new ReadableStream({async start(controller){for(const value of pieces){controller.enqueue(encoder.encode(JSON.stringify({type:'delta',value})+'\\n'));await new Promise(r=>setTimeout(r,3));}controller.enqueue(encoder.encode(JSON.stringify({type:'done'})+'\\n'));controller.close();}});
      const started=performance.now();
      try{
        await consumeTutorResponse(new Response(stream),live);
        const result={events:pieces.length,renders,elapsed_ms:performance.now()-started,ticks,
          complete:live.answer===content&&output.dataset.rawText===content,math:output.querySelectorAll('.katex').length,
          script_executed:!!window.badStreamScript,timer_cleared:!live.paintTimer};
        // Switching chats must cancel an old chat's pending paint.
        live.answer+=' additional';paintLiveReply(live);
        live.request={...request,conversation_id:'a-different-chat'};const retained=output.dataset.rawText;
        await new Promise(r=>setTimeout(r,160));result.detached_reply_unchanged=output.dataset.rawText===retained&&!live.paintTimer;
        return result;
      }finally{clearInterval(tick);clearTimeout(live.paintTimer);renderLessonText=original;output.parentElement.remove();}
    })()`,true);
    fs.writeFileSync(path.join(root,'metrics.json'),JSON.stringify(result,null,2));
    assert.ok(result.events>100,JSON.stringify(result));assert.ok(result.renders<result.events/3,JSON.stringify(result));
    assert.ok(result.complete&&result.timer_cleared&&result.detached_reply_unchanged);
    assert.equal(result.math,30);assert.equal(result.script_executed,false);assert.ok(result.ticks>20);
    assert.equal((await win.webContents.executeJavaScript(`api('/__display_test__/state')`)).model_calls,0);assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({passed:true,...result,model_calls:0,errors},null,2));
    app.exit(0);
  }catch(error){console.error(error);fs.writeFileSync(path.join(root,'failure.txt'),error.stack);app.exit(1);}
});
