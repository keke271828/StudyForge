const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const win = new BrowserWindow({show:false,width:1440,height:960,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,backgroundThrottling:false,offscreen:true}});
  const failures = [];
  win.webContents.on('console-message', (_event, level, text) => {if (level===3) failures.push(text);});
  try {
    await win.loadURL('http://127.0.0.1:8784');
    for (let i=0;i<60;i++) {
      if(await win.webContents.executeJavaScript('Boolean(state.project && state.settings)'))break;
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    const result = await win.webContents.executeJavaScript(`(async () => {
      if (!state.settings) throw new Error('页面初始化未完成');
      const selected = generationSelection();
      if (selected.model !== currentModel() || selected.reasoning_effort !== currentEffort() || selected.generation_quality !== 'custom') throw new Error('生成模型没有跟随导师');
      if (document.getElementById('generationModel') || document.getElementById('generationQuality')) throw new Error('仍显示独立文档模型');
      const toggle=document.getElementById('allowWebVideo');toggle.checked=true; await toggle.onchange();
      const config=await api('/api/settings');if(!config.agent_web_video_enabled) throw new Error('视频开关未保存');
      toggle.checked=false;await toggle.onchange();
      const content=message('assistant');
      renderLessonText(content, '# 统一导师\\n\\n行内 $x^2$；独立：\\n\\n$$F=ma$$\\n\\n[成果](/api/artifacts/'+'a'.repeat(32)+'/download)\\n\\n![学习图片](/api/agent/assets/'+'a'.repeat(32)+'/image)\\n\\n![外部图片](https://example.org/a.png)\\n\\n<script>alert(1)</script>');
      const formulas=content.querySelectorAll('.katex').length;
      if(formulas!==2 || content.querySelector('.katex-error') || content.querySelector('script'))throw new Error('Markdown 或公式渲染失败');
      if(content.querySelectorAll('img').length!==1 || !content.querySelector('a[download]'))throw new Error('图片或成果链接范围错误');
      showToolActivity(content,{tool:'sf_read_source',status:'completed'});
      if(!content.parentElement.querySelector('.tool-activity').textContent.includes('读取资料 · 完成'))throw new Error('没有工具状态');
      content.querySelectorAll('img').forEach(el=>el.remove());
      document.querySelector('[data-view="settings"]').click(); await new Promise(resolve=>setTimeout(resolve,500));
      if(!document.getElementById('view-settings').classList.contains('active') || getComputedStyle(document.getElementById('view-settings')).display==='none')throw new Error('设置页没有实际打开');
      if(getComputedStyle(document.getElementById('view-study')).display!=='none')throw new Error('学习页遮挡设置页');
      if(!document.getElementById('agentReadRoots') || !document.getElementById('imageModel'))throw new Error('没有工具设置');
      return {same_ai_selection:true,video_toggle_saved:true,formulas,trusted_image_only:true,tool_status:true,settings:true};
    })()`);
    await new Promise(resolve=>setTimeout(resolve,600));
    fs.writeFileSync(path.join(__dirname,'..','build','shared-agent-settings.png'),(await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG());
    console.log(JSON.stringify({result,console_errors:failures}));
    if(failures.some(text=>!text.includes('404')))throw new Error('页面报错');
    win.destroy();app.quit();
  }catch(error){console.error(error);win.destroy();app.exit(1);}
});
