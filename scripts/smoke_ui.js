const { app, BrowserWindow, clipboard, ipcMain } = require('electron');
const path = require('node:path');
const { registerClipboardHandler } = require('../desktop/clipboard');

app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const testUrl = process.env.STUDYFORGE_TEST_URL || 'http://127.0.0.1:8768';
  registerClipboardHandler(ipcMain, clipboard, new URL(testUrl).origin);
  const window = new BrowserWindow({ show: false, width: 1440, height: 940,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true,
      preload: path.join(__dirname, '..', 'desktop', 'preload.js') } });
  try {
    await window.loadURL(testUrl);
    await new Promise(resolve => setTimeout(resolve, 1000));
    const formVisible = await window.webContents.executeJavaScript(
      "document.getElementById('newProject').click(); !document.getElementById('projectForm').hidden");
    if (!formVisible) throw new Error('新建项目表单未显示');
    await window.webContents.executeJavaScript(
      "document.getElementById('projectName').value='界面验收项目'; document.getElementById('projectForm').requestSubmit()");
    await new Promise(resolve => setTimeout(resolve, 1200));
    const result = await window.webContents.executeJavaScript(`(() => {
      const projectCreated = [...document.querySelectorAll('.navigation-project')].some(x => x.textContent.includes('界面验收项目'));
      document.querySelector('[data-view="sources"]').click();
      const libraryUrl = Boolean(document.getElementById('libraryUrlForm'));
      document.querySelector('[data-view="study"]').click();
      document.getElementById('attachUrl').click();
      const composerUrl = !document.getElementById('composerUrlForm').hidden;
      document.querySelector('[data-view="settings"]').click();
      return {projectCreated, libraryUrl, composerUrl,
        codexModelInput: Boolean(document.getElementById('codexModel')),
        codexSelected: document.getElementById('provider').value === 'codex'};
    })()`);
    await new Promise(resolve => setTimeout(resolve, 400));
    result.localDefaultVisible = await window.webContents.executeJavaScript(
      "document.getElementById('codexModelHelp').textContent.includes('对话') && document.getElementById('codexModelHelp').textContent.includes('生成')");
    const workflow = await window.webContents.executeJavaScript(`(async () => {
      document.querySelector('[data-view="sources"]').click();
      document.getElementById('categoryName').value = '动力学';
      document.getElementById('createCategoryForm').requestSubmit();
      for (let i = 0; i < 30 && !document.querySelector('[data-manager-select]'); i++)
        await new Promise(resolve => setTimeout(resolve, 100));
      const categoryId = document.querySelector('[data-manager-select]')?.dataset.managerSelect;
      if (!categoryId) return { categoryCreated: false };
      const projectId = document.querySelector('.navigation-project.active').dataset.navId;
      const form = new FormData(); form.append('project_id', projectId);
      form.append('category_id', categoryId);
      form.append('file', new Blob(['F = ma'], {type:'text/plain'}), 'newton.txt');
      const imported = await (await fetch('/api/import/file', {method:'POST', body:form})).json();
      let ready = false;
      for (let i = 0; i < 50; i++) {
        const job = await (await fetch('/api/jobs/' + imported.job_id)).json();
        if (job.status === 'completed') { ready = true; break; }
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      await refreshSources();
      document.querySelector('[data-view="study"]').click();
      const quick = document.querySelector('[data-toggle-category="' + categoryId + '"]');
      const sourceVisible = document.getElementById('quickSources').textContent.includes('newton.txt');
      quick?.click();
      const categorySelected = state.selected.has(imported.source_id);
      document.getElementById('sourceSearch').value = 'newton';
      document.getElementById('sourceSearch').dispatchEvent(new Event('input'));
      const searchWorks = document.getElementById('quickSources').textContent.includes('newton.txt');
      document.getElementById('sourceSearch').value = '';
      document.getElementById('sourceSearch').dispatchEvent(new Event('input'));
      return {categoryCreated: true, importReady: ready, sourceVisible, categorySelected, searchWorks};
    })()`);
    Object.assign(result, workflow);
    const preferences = await window.webContents.executeJavaScript(`(async () => {
      document.querySelector('[data-view="settings"]').click();
      await new Promise(resolve => setTimeout(resolve, 300));
      const defaultsVisible = document.getElementById('defaultReviewMode').value
        === document.getElementById('reviewMode').value
        && [...document.getElementById('reviewMode').options].some(option => option.value === 'fast');
      const guidesVisible = Boolean(document.getElementById('copyCodexPrompt'))
        && Boolean(document.getElementById('copyDshPrompt'));
      document.getElementById('defaultReviewMode').value = 'balanced';
      document.getElementById('defaultExplanationStyle').value = 'academic';
      document.getElementById('defaultOutputLanguage').value = 'bilingual';
      document.getElementById('codexGenerationModel').value = 'gpt-6-luna';
      await document.getElementById('saveSettings').onclick();
      const defaultsApplied = document.getElementById('reviewMode').value === 'balanced'
        && document.getElementById('explanationStyle').value === 'academic'
        && document.getElementById('outputLanguage').value === 'bilingual'
        && state.settings.codex_generation_model === 'gpt-6-luna';
      return {defaultsVisible, guidesVisible, defaultsApplied};
    })()`);
    Object.assign(result, preferences);
    const originalClipboard = await clipboard.readText();
    try {
      await window.webContents.executeJavaScript("document.getElementById('copyCodexPrompt').onclick()");
      result.codexPromptCopied = (await clipboard.readText()).includes('studyforge MCP 的 list_projects');
      await window.webContents.executeJavaScript("document.getElementById('copyDshPrompt').onclick()");
      result.dshPromptCopied = (await clipboard.readText()).includes('mcp__studyforge__list_projects');
    } finally { await clipboard.writeText(originalClipboard); }
    const studyControls = await window.webContents.executeJavaScript(`(async () => {
      document.querySelector('[data-view="study"]').click();
      const catalog = await loadCodexCatalog(true);
      const modelListWorks = catalog.models.some(model => model.id === 'gpt-6-luna');
      document.getElementById('studyModel').value = 'gpt-6-luna';
      document.getElementById('studyModel').dispatchEvent(new Event('change'));
      document.getElementById('reasoningEffort').value = 'high';
      document.getElementById('reasoningEffort').dispatchEvent(new Event('change'));
      const effortWorks = !document.getElementById('reasoningEffort').disabled
        && document.getElementById('reasoningEffort').value === 'high';
      const originalFetch = window.fetch;
      let chatPayload, generatePayload;
      window.fetch = async (...args) => {
        const path = String(args[0]);
        if (path === '/api/chat/stream') {
          chatPayload = JSON.parse(args[1].body);
          return new Response('{"type":"conversation","value":"mock-chat"}\\n{"type":"delta","value":"收到"}\\n{"type":"done","value":true}\\n', {headers:{'content-type':'application/x-ndjson'}});
        }
        if (path === '/api/generate') {
          generatePayload = JSON.parse(args[1].body);
          return new Response(JSON.stringify({job_id:'mock-job'}), {headers:{'content-type':'application/json'}});
        }
        if (path === '/api/jobs/mock-job') {
          return new Response(JSON.stringify({status:'completed',kind:'generate',progress:100,result:{}}), {headers:{'content-type':'application/json'}});
        }
        return originalFetch(...args);
      };
      document.getElementById('prompt').value = '解释牛顿第二定律';
      await document.getElementById('sendMessage').onclick();
      await document.getElementById('generate').onclick();
      window.fetch = originalFetch;
      const modelAndEffortSent = chatPayload?.model === 'gpt-6-luna' && chatPayload?.reasoning_effort === 'high'
        && generatePayload?.generation_quality === 'quality' && generatePayload?.model === null
        && generatePayload?.reasoning_effort === null;
      const browserImportVisible = document.querySelectorAll('.browser-import-button').length === 2;
      document.querySelector('[data-view="study"]').click();
      const transfer = new DataTransfer();
      transfer.items.add(new File(['E = mc^2'], 'dragged.txt', {type:'text/plain'}));
      const target = document.getElementById('studyDropZone');
      target.dispatchEvent(new DragEvent('dragenter', {bubbles:true,cancelable:true,dataTransfer:transfer}));
      const dragOverlayVisible = !document.getElementById('studyDropOverlay').hidden;
      target.dispatchEvent(new DragEvent('drop', {bubbles:true,cancelable:true,dataTransfer:transfer}));
      const projectId = state.project.id;
      let studyDropImported = false;
      for (let i=0; i<50; i++) {
        const sources = await (await originalFetch('/api/projects/' + projectId + '/sources')).json();
        if (sources.some(source => source.name === 'dragged.txt' && source.status === 'ready')) { studyDropImported = true; break; }
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      return {modelListWorks, effortWorks, modelAndEffortSent, browserImportVisible, dragOverlayVisible, studyDropImported};
    })()`);
    Object.assign(result, studyControls);
    await new Promise(resolve => setTimeout(resolve, 450));
    if (process.env.STUDYFORGE_SCREENSHOT_PATH) {
      const image = await window.webContents.capturePage();
      require('node:fs').writeFileSync(process.env.STUDYFORGE_SCREENSHOT_PATH, image.toPNG());
    }
    result.progressAutoUpdates = await window.webContents.executeJavaScript(`(async () => {
      const originalFetch = window.fetch;
      let polls = 0;
      window.fetch = async (...args) => {
        if (String(args[0]).includes('/jobs')) {
          polls += 1;
          return new Response(JSON.stringify([{id:'sample',kind:'generate',status:'running',
            progress:polls === 1 ? 10 : 59,stage:polls === 1 ? '读取原资料' : '事实与推导审查',
            created_at:new Date().toISOString()}]), {headers:{'content-type':'application/json'}});
        }
        return originalFetch(...args);
      };
      document.querySelector('[data-view="artifacts"]').click();
      await new Promise(resolve => setTimeout(resolve, 1900));
      const updated = polls >= 2 && document.getElementById('jobs').textContent.includes('事实与推导审查')
        && document.getElementById('jobs').textContent.includes('59%');
      window.fetch = originalFetch;
      document.querySelector('[data-view="study"]').click();
      return updated;
    })()`);
    if (Object.values(result).some(value => !value)) throw new Error(JSON.stringify(result));
    console.log(JSON.stringify(result));
  } finally {
    window.destroy();
    app.quit();
  }
}).catch(error => { console.error(error); app.exit(1); });
