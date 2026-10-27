/* Real Chromium parity and append workload. No model or learning database. */
const {app,BrowserWindow}=require('electron'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url'),root=path.resolve(__dirname,'..'),folder=path.join(root,'build',process.argv[2]||'history-performance-20261011-1');
fs.mkdirSync(folder,{recursive:true});app.setPath('userData',path.join(folder,'browser'));app.disableHardwareAcceleration();
const asset=name=>pathToFileURL(path.join(root,'web',name)).href;
fs.writeFileSync(path.join(folder,'fixture.html'),`<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="${asset('vendor/katex.css')}"><style>body{background:#f3f5ef;color:#233d31;font:16px/1.8 sans-serif}.host{width:850px;height:600px;overflow:auto;margin:auto}.message{padding:15px}.message-content{min-width:0}.katex-display{overflow:auto}</style><script src="${asset('vendor/marked.js')}"></script><script src="${asset('vendor/purify.js')}"></script><script src="${asset('vendor/katex.js')}"></script><script src="${asset('lesson_render.js')}"></script><script src="${asset('message_history.js')}"></script><div id="host" class="host"></div>`);
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1100,height:800,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
 const run=code=>win.webContents.executeJavaScript(code);
 try{
  await win.loadFile(path.join(folder,'fixture.html'));
  await run(`window.host=document.getElementById('host');window.make=row=>{const node=document.createElement('div');node.className='message '+row.role;node.dataset.messageId=row.id;const body=document.createElement('div');body.className='message-content';if(row.role==='user')body.textContent=row.content;else renderLessonText(body,row.content);node.append(body);return node;};window.rows=Array.from({length:60},(_,i)=>({id:'saved-'+i,role:i%2?'assistant':'user',content:i%2?'## 思路 '+i+'\\n\\n先确认目标，再选择让两个开邻域不相交的半径。\\n\\n$$\\\\varepsilon=\\\\frac{b-a}{2}\\\\quad N=\\\\max\\\\{N_1,N_2\\\\}$$\\n\\n这只是方便的选择，同样可以取 $\\\\frac{b-a}{3}$。\\n\\n> 来源：自编测试，不是教材原文。\\n\\n| 对象 | 作用 |\\n|---|---|\\n| $a,b$ | 两个不同的候选极限 |':'为什么需要解释这个条件？ '+i}));
   window.legacy=messages=>{studyforgeMessageHistory.reset(host);host.replaceChildren();for(const row of messages){host.append(make(row));host.scrollTop=host.scrollHeight;}};window.optimized=messages=>{studyforgeMessageHistory.sync(host,messages,make,{scope:'same-chat'});host.scrollTop=host.scrollHeight;};true;`);
  const semantic=await run(`(()=>{legacy(rows);const expected=host.innerHTML;host.replaceChildren();optimized(rows);if(host.innerHTML!==expected)throw new Error('Rendered history differs');if(host.querySelector('.katex-error')||host.querySelectorAll('.katex').length<60)throw new Error('Math not rendered correctly');const old=host.children[1],text=old.querySelector('p').firstChild,range=document.createRange();range.selectNodeContents(text);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);const selected=selection.toString();
   const card=document.createElement('form');card.className='lesson-questionnaire';const input=document.createElement('input');input.value='尚未提交的困惑';card.append(input);host.append(card);input.focus();const extra={id:'new',role:'assistant',content:'## 新结果\\n\\n$$x^2+y^2=1$$'};
   let result=studyforgeMessageHistory.sync(host,[...rows,extra],make,{scope:'same-chat',preserve:[card]});if(old!==host.children[1]||input.value!=='尚未提交的困惑'||document.activeElement!==input)throw new Error('A stable answer or draft was rebuilt');if(result.rendered!==1||result.retained!==60)throw new Error('Append rendered history again');
   input.blur();selection.removeAllRanges();selection.addRange(range);studyforgeMessageHistory.sync(host,[...rows,extra],make,{scope:'same-chat',preserve:[card]});if(selection.toString()!==selected)throw new Error('Selection detached');
   const changed=[...rows,{...extra,content:'修订后的同一消息 $x+y=1$'}];result=studyforgeMessageHistory.sync(host,changed,make,{scope:'same-chat',preserve:[card]});if(result.rendered!==1||!host.textContent.includes('修订后'))throw new Error('Same-ID revision ignored');
   result=studyforgeMessageHistory.sync(host,rows.slice(0,4),make,{scope:'same-chat'});if(host.children.length!==4||host.contains(card))throw new Error('Removed messages or widget remained');
   result=studyforgeMessageHistory.sync(host,[{id:rows[0].id,role:'user',content:'另一项目的独立对话'}],make,{scope:'other-chat'});if(host.children.length!==1||host.textContent.includes('候选极限'))throw new Error('Chat scope mixed');
   return {parity:true,stable_dom:true,selection_retained:true,unsent_draft_retained:true,same_id_revision:true,deletion:true,scope_isolated:true};})()`);
  win.webContents.debugger.attach('1.3');const measures=[];
  for(const mode of ['legacy','optimized','optimized','legacy']){
   await run('studyforgeMessageHistory.reset(host);host.replaceChildren()');await win.webContents.debugger.sendCommand('HeapProfiler.collectGarbage');
   const initial=await run(`(()=>{const start=performance.now();${mode}(rows);return performance.now()-start;})()`);let heapPeak=0;const frames=[];
   for(let step=1;step<=6;step++){
    frames.push(await run(`(()=>{const input=[...rows,...Array.from({length:${step}},(_,i)=>({id:'addition-'+i,role:'assistant',content:'新增的讲解 $a+b=c$。'}))],start=performance.now();${mode}(input);const h=host.scrollHeight;return performance.now()-start;})()`));
    const heap=await win.webContents.debugger.sendCommand('Runtime.getHeapUsage');heapPeak=Math.max(heapPeak,heap.usedSize+(heap.embedderHeapUsedSize||0));
   }
   measures.push({mode,initial_ms:initial,update_ms:frames.reduce((a,b)=>a+b,0),max_update_ms:Math.max(...frames),heap_peak_bytes:heapPeak});
  }
  const average=mode=>{const items=measures.filter(x=>x.mode===mode);return Object.fromEntries(['initial_ms','update_ms','heap_peak_bytes'].map(key=>[key,items.reduce((a,b)=>a+b[key],0)/items.length]));};
  const before=average('legacy'),after=average('optimized');assert(after.update_ms<before.update_ms);
  fs.writeFileSync(path.join(folder,'report.json'),JSON.stringify({passed:true,semantic,measures,before,after,update_cpu_reduction_percent:100*(1-after.update_ms/before.update_ms),heap_reduction_percent:100*(1-after.heap_peak_bytes/before.heap_peak_bytes),scope:'Local rendering of 60 saved public messages plus six append updates. JS/embedder heap; not whole application RSS or AI generation latency.'},null,2));
  win.destroy();app.quit();
 }catch(error){fs.writeFileSync(path.join(folder,'report.json'),JSON.stringify({passed:false,error:String(error.stack||error)},null,2));win.destroy();app.exit(1);}
});
