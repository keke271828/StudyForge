const {app, BrowserWindow, session} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const codexRequests = [], errors = [];
  session.defaultSession.webRequest.onBeforeRequest({urls:['http://127.0.0.1:8784/api/codex/*']}, (details, callback) => {
    codexRequests.push(details.url); callback({cancel:true});
  });
  const win = new BrowserWindow({show:false,width:1440,height:960,
    webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,backgroundThrottling:false,offscreen:true}});
  win.webContents.on('console-message', (_event, level, text) => {if(level===3) errors.push(text);});
  try {
    await win.loadURL('http://127.0.0.1:8784');
    for(let i=0;i<60;i++) {
      if(await win.webContents.executeJavaScript("Boolean(state.settings && state.project && $('modelStatus').textContent.includes('无需打开 Codex'))")) break;
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    const result = await win.webContents.executeJavaScript(`(async () => {
      if($('provider').value!=='deepseek' || !$('modelStatus').textContent.includes('无需打开 Codex')) throw new Error('没有独立 DeepSeek 状态：'+$('provider').value+' / '+$('modelStatus').textContent);
      if(state.codexCatalog) throw new Error('DeepSeek 初始化不应读取 Codex 目录');
      state.selected.clear();state.reading=null;state.conversation=null;
      const originalFetch=window.fetch;let sawRetry=false;
      const observer=new MutationObserver(() => {
        if(document.querySelector('.reply-status')?.textContent.includes('自动重试')) sawRetry=true;
      });
      observer.observe($('messages'),{childList:true,subtree:true,characterData:true});
      window.fetch=async (url,options) => {
        if(url!=='/api/chat/stream') return originalFetch(url,options);
        const encode=events=>new TextEncoder().encode(events.map(event=>JSON.stringify(event)).join('\\n')+'\\n');
        return new Response(new ReadableStream({start(controller) {
          controller.enqueue(encode([{type:'conversation',value:'ui-test'}, {type:'delta',value:'不完整文字'},
            {type:'replace',value:''},{type:'status',value:'DeepSeek 响应未完成，正在自动重试一次…'}]));
          setTimeout(() => {
            controller.enqueue(encode([{type:'tool',value:{tool:'sf_read_source',status:'completed'}},
              {type:'delta',value:'完整回答。'},{type:'replace',value:'完整回答。'},{type:'done',value:true}]));
            controller.close();
          },300);
        }}),{headers:{'Content-Type':'application/x-ndjson'}});
      };
      $('prompt').value='界面恢复测试';await $('sendMessage').onclick();
      window.fetch=originalFetch;observer.disconnect();
      const reply=$('messages').lastElementChild;
      if(!sawRetry || reply.textContent.includes('不完整文字') || !reply.textContent.includes('完整回答')) throw new Error('重试状态或正文替换失败');
      if(!reply.querySelector('.reply-status')?.hidden) throw new Error('完成后仍显示重试');
      const tool=reply.querySelector('.tool-activity:not(.reply-status)');
      if(tool?.hidden || !tool?.textContent.includes('读取资料 · 完成')) throw new Error('恢复状态覆盖了工具状态');
      let recovering=true;
      window.fetch=async (url,options) => {
        if(url.endsWith('/jobs')) return new Response(JSON.stringify([{id:'progress-test',kind:'generate',status:'running',
          progress:53,stage:'撰写系统讲解',request_status:recovering?'DeepSeek 正在自动重试一次…':null,created_at:new Date().toISOString()}]),
          {headers:{'Content-Type':'application/json'}});
        return originalFetch(url,options);
      };
      await refreshArtifacts();
      let card=$('jobs').querySelector('.job-card');
      if(!card?.textContent.includes('自动重试') || !card.textContent.includes('撰写系统讲解') ||
        card.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')!=='53' ||
        !card.querySelector('[data-generation-control]')) throw new Error('生成重试进度卡错误');
      recovering=false;await refreshArtifacts();window.fetch=originalFetch;
      card=$('jobs').querySelector('.job-card');
      if(card.textContent.includes('自动重试') || !card.textContent.includes('撰写系统讲解')) throw new Error('生成恢复后重试状态未清除');
      return {deepseek_selected:true,no_codex_catalog:true,retry_visible:true,partial_reply_replaced:true,tool_status_preserved:true,generation_retry_visible:true};
    })()`);
    if(codexRequests.length || errors.length) throw new Error(JSON.stringify({codexRequests,errors}));
    fs.writeFileSync(path.join(__dirname,'..','build','deepseek-ui-result.json'),JSON.stringify({result,codexRequests,errors},null,2));
    console.log(JSON.stringify({result,codexRequests,errors}));
    win.destroy();app.quit();
  } catch(error) {console.error(error);win.destroy();app.exit(1);}
});
