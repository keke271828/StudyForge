/* Actual Chromium rendering: exact output parity and long math-answer load.
 * Uses local public fixtures only, no model, user DB, or network requests. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'build',process.argv[2]||'ui-performance-20261010-1');
assert(folder.startsWith(path.join(root,'build')+path.sep));fs.mkdirSync(folder,{recursive:true});
app.setPath('userData',path.join(folder,'electron-profile'));app.disableHardwareAcceleration();
const url=file=>pathToFileURL(path.join(root,'web',file)).href;
fs.writeFileSync(path.join(folder,'renderer.html'),`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><link rel="stylesheet" href="${url('vendor/katex.css')}"><style>body{font:16px/1.8 sans-serif;width:850px;margin:auto}.lesson-quote{background:#eef4ee;padding:12px}.display-math{display:block}.lesson-explanation pre{white-space:pre-wrap}</style><script src="${url('vendor/marked.js')}"></script><script src="${url('vendor/purify.js')}"></script><script src="${url('vendor/katex.js')}"></script><script src="${url('lesson_render.js')}"></script><div id="expected"></div><div id="actual"></div></html>`);
let win;
const run=code=>win.webContents.executeJavaScript(code);
const write=(name,value)=>fs.writeFileSync(path.join(folder,name),JSON.stringify(value,null,2));
app.whenReady().then(async()=>{
 win=new BrowserWindow({show:false,width:1150,height:900,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
 try{
  await win.loadFile(path.join(folder,'renderer.html'));
  const before=fs.readFileSync(path.join(folder,'lesson_render.before.js'),'utf8');
  await run('window.baselineRender=(function(){'+before+'\nreturn renderLessonText;})();true;');
  const fixtures=[
   '# 极限唯一性\n\n为什么取 $\\varepsilon=(b-a)/2$？\n\n$$|x_n-a|<\\varepsilon$$\n\n**构造动机**：两个开邻域不相交。',
   '> 原文 $\\forall\\varepsilon>0$\n> \n> 还需 $N=\\max(N_1,N_2)$。\n\n解释：同时成立。',
   '1. 定义 $a$\n2. 方法\n   - 一个条件\n   - 第二个条件\n\n3. 结论\n\n---\n\n下一节',
   '| 对象 | 公式 |\n|---|---|\n| 数列 | $x_n$ |\n| 间距 | $b-a$ |\n\n表格之外。',
   '```python\nprint("$a$")\n\n# blank line within code\n```\n\n`$a$` 是代码。\n\n\\[a^2+b^2=c^2\\]',
   '先看 [定义][source]，再看 $a$。\n\n[source]: https://example.org/definition "标题"\n',
   'STUDYFORGEMATHZ0Q 不能被当成公式。\n\n$$\\frac{1}{2}$$\n\n<img src="https://example.org/a.png" onerror="alert(1)">\n\n[内部下载](/api/artifacts/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/download)',
   '~~~text\n$$literal$$\n~~~\n\n数学 \\(x+y\\) 与 emoji 🧠。\n\n**未闭合的粗体和 $x'
  ];
  const parity=await run(`(()=>{const fixtures=${JSON.stringify(fixtures)},a=document.getElementById('actual'),b=document.getElementById('expected');let checks=0;
    for(const text of fixtures){a.replaceChildren();for(let end=1;end<=text.length;end+=7){const value=text.slice(0,end);baselineRender(b,value);renderLessonStream(a,value);if(a.innerHTML!==b.innerHTML)throw new Error('Stream differs at '+checks+' '+JSON.stringify(value));checks++;}baselineRender(b,text);renderLessonStream(a,text);if(a.innerHTML!==b.innerHTML)throw new Error('Completed fixture differs');checks++;}
    for(const text of ['$a$','$b$','先前回复全部改写。','$a^2$','']){baselineRender(b,text);renderLessonStream(a,text);if(a.innerHTML!==b.innerHTML)throw new Error('Replacement changed math incorrectly');checks++;}
    renderLessonStream(a,'第一段 $a$。\\n\\n第二段开始');const held=a.firstChild.firstChild;renderLessonStream(a,'第一段 $a$。\\n\\n第二段开始，追加内容');if(a.firstChild.firstChild!==held)throw new Error('Stable block replaced');
    renderLessonText(a,'恢复已保存的正文');renderLessonStream(a,'恢复后的追加内容');baselineRender(b,'恢复后的追加内容');if(a.innerHTML!==b.innerHTML)throw new Error('Restored DOM cache stale');
    return {checks,stable_node_retained:true,raw_html_escaped:!a.querySelector('img[onerror]')};})()`);
  await run(`window.loadText=Array.from({length:100},(_,i)=>'## 第 '+(i+1)+' 个推理环节\\n\\n直觉：把两个不同的极限放在数轴上，取共同的正数 $\\\\varepsilon=\\\\frac{b-a}{2}$。两个开邻域可以接触边界，却不包含边界。先明确目标，再找能满足目标的参数。\\n\\n$$|x_n-a|<\\\\frac{b-a}{2}\\\\quad\\\\Longrightarrow\\\\quad x_n<\\\\frac{a+b}{2}$$\\n\\n由 $N=\\\\max\\\\{N_1,N_2\\\\}$ 保证两个结论同时成立，不能遗漏量词。\\n\\n> 来源：自编测试段落，保留适用条件。\\n\\n').join('');window.perfStep=(mode,i)=>{const a=document.getElementById('actual'),value=loadText.slice(0,Math.ceil(loadText.length*i/80));const started=performance.now();const result=(mode==='baseline'?baselineRender:renderLessonStream)(a,value);const height=a.offsetHeight;return {ms:performance.now()-started,retained:result?.retained||0,rendered:result?.rendered||0,nodes:a.querySelectorAll('*').length,height};};document.getElementById('expected').replaceChildren();`);
  win.webContents.debugger.attach('1.3');
  const measures=[];
  for(const mode of ['baseline','stream','stream','baseline']){
   await run("document.getElementById('actual').replaceChildren()");
   await win.webContents.debugger.sendCommand('HeapProfiler.collectGarbage');
   let heapPeak=0,domPeak=0,retained=0,rendered=0;const timings=[];
   for(let i=1;i<=80;i++){
    const result=await run(`perfStep('${mode}',${i})`);timings.push(result.ms);domPeak=Math.max(domPeak,result.nodes);retained+=result.retained;rendered+=result.rendered;
    const heap=await win.webContents.debugger.sendCommand('Runtime.getHeapUsage');heapPeak=Math.max(heapPeak,heap.usedSize+ (heap.embedderHeapUsedSize||0));
   }
   const finalHTML=await run("document.getElementById('actual').innerHTML");
   if(measures.length)assert.equal(finalHTML,measures[0]._html);
   measures.push({mode,frames:80,total_render_ms:timings.reduce((a,b)=>a+b,0),max_frame_ms:Math.max(...timings),frames_over_50ms:timings.filter(x=>x>50).length,heap_peak_bytes:heapPeak,dom_peak_nodes:domPeak,retained,rendered,_html:finalHTML});
  }
  const average=mode=>{const selected=measures.filter(x=>x.mode===mode);return Object.fromEntries(['total_render_ms','max_frame_ms','heap_peak_bytes'].map(key=>[key,selected.reduce((sum,x)=>sum+x[key],0)/selected.length]));};
  const baseline=average('baseline'),stream=average('stream');
  const result={passed:true,parity,source_characters:await run('loadText.length'),baseline,stream,render_cpu_reduction_percent:100*(1-stream.total_render_ms/baseline.total_render_ms),heap_peak_reduction_percent:100*(1-stream.heap_peak_bytes/baseline.heap_peak_bytes),runs:measures.map(({_html,...row})=>row),scope:'Local Chromium math Markdown rendering; measured JS plus embedder heap, not total application RAM or model generation time.'};
  write('report.json',result);console.log(JSON.stringify(result));win.destroy();app.quit();
 }catch(error){write('report.json',{passed:false,error:error.stack||String(error)});console.error(error);win?.destroy();app.exit(1);}
});
