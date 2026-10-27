const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const win = new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});
  const errors = [];
  win.webContents.on('console-message', (_event, level, text) => {if (level === 3 && !text.includes('404')) errors.push(text);});
  try {
    await win.loadURL('http://127.0.0.1:8789');
    const result = await win.webContents.executeJavaScript(`(async () => {
      for (let i=0;i<80 && !state.project;i++) await new Promise(r=>setTimeout(r,100));
      if(!state.project) throw new Error('项目未就绪');
      showView('profile'); await refreshProfile();
      const panel = document.getElementById('view-profile');
      if(!panel.classList.contains('active') || getComputedStyle(panel).display==='none')throw new Error('画像页未显示');
      if(!document.getElementById('memoryStatus').textContent.includes('今日 1/6'))throw new Error('后台额度状态缺失');
      if(!document.getElementById('profile').textContent.includes('尚无评估分数'))throw new Error('导入/讨论虚增分数');
      const cards = [...document.querySelectorAll('.memory-card')];
      if(cards.length < 3 || !cards.some(x=>x.textContent.includes('暂定')) || !cards.some(x=>x.textContent.includes('接触记录')))throw new Error('记忆未分类');
      cards[0].querySelector('details').open=true;
      if(!cards[0].querySelector('blockquote').textContent)throw new Error('缺少证据原话');
      document.querySelector('.memory-settings').open=true;
      document.getElementById('backgroundLearningEnabled').checked=false;
      await document.getElementById('saveMemorySettings').onclick();
      const saved = await api('/api/settings');
      if(saved.background_learning_enabled!==false || !document.getElementById('memoryStatus').textContent.includes('已关闭'))throw new Error('后台开关保存失败');
      document.getElementById('backgroundLearningEnabled').checked=true;
      await document.getElementById('saveMemorySettings').onclick();
      document.getElementById('backgroundLearningInterval').value='20';
      await refreshProfile(false);
      if(document.getElementById('backgroundLearningInterval').value!=='20')throw new Error('轮询覆盖未保存的设置');
      document.getElementById('backgroundLearningInterval').value='15';
      const overflowing = [...panel.querySelectorAll('.memory-card,.memory-settings')].filter(el=>el.scrollWidth>el.clientWidth+2);
      if(overflowing.length)throw new Error('画像卡片内容溢出');
      return {cards:cards.length,evidence_visible:true,no_inflated_scores:true,toggle_saved:true,unsaved_settings_preserved:true};
    })()`);
    const screenshot = path.join(__dirname,'..','build','learning-memory-profile.png');
    fs.writeFileSync(screenshot,(await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG());
    if(errors.length)throw new Error(errors.join('; '));
    console.log(JSON.stringify({result,screenshot,console_errors:errors}));
    win.destroy();app.quit();
  } catch(error) {console.error(error);win.destroy();app.exit(1);}
});
