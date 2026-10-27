// Actual Chromium downloads against the frozen backend, using isolated fixtures.
const { app, BrowserWindow, session } = require('electron');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');

const root = process.env.STUDYFORGE_DOWNLOAD_SMOKE_ROOT;
if (!root || !path.isAbsolute(root)) throw new Error('Set STUDYFORGE_DOWNLOAD_SMOKE_ROOT to the fixture directory.');
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'fixture.json'), 'utf8'));
app.setPath('userData', path.join(root, 'electron-profile'));
let backend;
app.on('before-quit', () => backend?.kill());

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

app.whenReady().then(async () => {
  const port = await freePort();
  const url = `http://127.0.0.1:${port}`;
  const executable = path.resolve(__dirname, '../dist/win-unpacked/resources/backend/StudyForgeBackend.exe');
  const log = fs.openSync(path.join(root, 'backend.log'), 'w');
  const command = process.env.STUDYFORGE_SMOKE_PYTHON || executable;
  const args = process.env.STUDYFORGE_SMOKE_PYTHON ? ['-m', 'studyforge.server'] : [];
  backend = spawn(command, args, { cwd: process.env.STUDYFORGE_SMOKE_PYTHON ? path.resolve(__dirname, '..') : root, windowsHide: true, stdio: ['ignore', log, log],
    env: { ...process.env, PYTHONUTF8: '1', STUDYFORGE_PORT: String(port),
      STUDYFORGE_PARENT_PID: String(process.pid), STUDYFORGE_DATA_DIR: path.join(root, 'data') } });
  fs.closeSync(log);
  let ready = false;
  for (let i = 0; i < 180; i++) {
    try { if ((await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(800) })).ok) { ready = true; break; } }
    catch (_) { /* Allow the frozen backend to start. */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  assert(ready, 'Frozen backend did not start');
  const window = new BrowserWindow({ show: false, width: 1480, height: 960, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
  window.webContents.on('console-message', (_event, level, message) => {
    if (level >= 2) console.error('Renderer:', message);
  });
  await window.loadURL(url);
  const artifacts = await (await fetch(`${url}/api/projects/${fixture.project_id}/artifacts`)).json();
  let linksReady = false;
  for (let i = 0; i < 100; i++) {
    if (await window.webContents.executeJavaScript(`document.querySelectorAll('#artifacts a').length === ${artifacts.length}`)) {
      linksReady = true; break;
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(linksReady, 'Artifact links did not render');
  const handoffView = await window.webContents.executeJavaScript(`(() => {
    const details = document.querySelector('.mentor-handoff'); details.open = true;
    return { text: details.textContent, unsafe: Boolean(details.querySelector('script,img,[onerror]')) };
  })()`);
  assert(handoffView.text.includes('导师已交接') && handoffView.text.includes('tutor-model')
    && handoffView.text.includes('你的原话') && handoffView.text.includes('讲解如何调整'));
  assert(!handoffView.unsafe && handoffView.text.includes('<script>alert(1)</script>'));
  await window.webContents.executeJavaScript(`document.querySelector('[data-generation-control="${fixture.pause_job}"][data-action="pause"]').click()`);
  let paused = false;
  for (let i = 0; i < 50; i++) {
    const job = await (await fetch(`${url}/api/jobs/${fixture.pause_job}`)).json();
    if (job.status === 'paused') { paused = true; break; }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(paused, 'Pause button did not pause the fixture task');
  let resumeReady = false;
  for (let i = 0; i < 50; i++) {
    resumeReady = await window.webContents.executeJavaScript(`Boolean(document.querySelector('[data-generation-control="${fixture.pause_job}"][data-action="resume"]'))`);
    if (resumeReady) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(resumeReady, 'Paused task did not render the Continue button');
  const pausedView = await window.webContents.executeJavaScript(`refreshArtifacts().then(() => {
    const button = document.querySelector('[data-generation-control="${fixture.pause_job}"][data-action="resume"]');
    return button.closest('.job-card').textContent;
  })`);
  assert(pausedView.includes('已暂停') && pausedView.includes('继续生成'));
  await window.webContents.executeJavaScript(`document.querySelector('[data-generation-control="${fixture.pause_job}"][data-action="resume"]').click()`);
  let resumed = false;
  for (let i = 0; i < 50; i++) {
    const job = await (await fetch(`${url}/api/jobs/${fixture.pause_job}`)).json();
    // The fixture intentionally has no original PDF. Resumption must reach
    // the source check and fail there, without any real model request.
    if (job.status === 'failed' && job.error.includes('原文件不存在：社会制度导论.pdf')) { resumed = true; break; }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(resumed, 'Continue button did not resume the fixture task');
  const mathContent = '# 公式与 Markdown 自检\n\n> 原文引用：$E=mc^2$\n\n**讲解**：速度 $v_0$，频率 \\(\\omega=\\sqrt{k/m}\\)。\n\n$$\\begin{aligned}E&=\\frac12mv^2\\\\F&=ma\\end{aligned}$$\n\n\\[x(t)=x_0\\cos(\\omega t)\\]\n\n|量|表达式|\n|---|---|\n|矩阵|$\\begin{pmatrix}1 & 2\\\\3 & 4\\end{pmatrix}$|\n\n- 条目一\n- 条目二\n\n```python\nprint("$not_math$")\n```\n\n<img src=x onerror=alert(1)>\n[危险链接](javascript:alert(1))';
  const rendering = await window.webContents.executeJavaScript(`(() => {
    const element = message('assistant', ${JSON.stringify(mathContent)});
    const quote = element.querySelector('.lesson-quote');
    const explanation = element.querySelector('.lesson-explanation');
    return { formulas: element.querySelectorAll('.katex').length,
      errors: element.querySelectorAll('.katex-error').length,
      headings: element.querySelectorAll('h1').length, lists: element.querySelectorAll('li').length,
      tables: element.querySelectorAll('table').length,
      code: element.querySelector('pre code').textContent,
      unsafe: Boolean(element.querySelector('img,script,[onerror],a[href^="javascript:"]')),
      colors: getComputedStyle(quote).color !== getComputedStyle(explanation).color,
      fonts: getComputedStyle(quote).fontFamily !== getComputedStyle(explanation).fontFamily,
      rawPreserved: element.dataset.rawText === ${JSON.stringify(mathContent)} };
  })()`);
  assert.equal(rendering.formulas, 6);
  assert.equal(rendering.errors, 0);
  assert.equal(rendering.headings, 1); assert.equal(rendering.tables, 1); assert.equal(rendering.lists, 2);
  assert(rendering.code.includes('$not_math$'));
  assert(!rendering.unsafe && rendering.colors && rendering.fonts && rendering.rawPreserved);
  await window.webContents.executeJavaScript(`document.fonts.ready.then(() => {
    document.getElementById('messages').scrollTop = 0;
  })`);
  await new Promise(resolve => setTimeout(resolve, 300));
  fs.writeFileSync(path.join(root, 'formula-preview.png'), (await window.webContents.capturePage(undefined, { stayHidden: true, stayAwake: true })).toPNG());
  fs.mkdirSync(path.join(root, 'downloads'), { recursive: true });
  const downloads = [];
  for (const [id, storedPath] of Object.entries(fixture.artifact_paths)) {
    const artifact = artifacts.find(row => row.id === id);
    const stored = fs.readFileSync(storedPath);
    const prefix = artifact.kind === 'explanation' ? '规训权力_AI讲解_' : '社会制度导论_配套习题';
    const result = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Download timed out')), 30000);
      session.defaultSession.once('will-download', (_event, item) => {
        try {
          const filename = item.getFilename();
          assert(filename.startsWith(prefix), `Unexpected desktop filename: ${filename}`);
          assert.equal(filename, artifact.download_filename);
          assert.equal(path.basename(filename), filename);
          const target = path.join(root, 'downloads', filename);
          item.setSavePath(target);
          item.once('done', (_done, state) => {
            clearTimeout(timer);
            try {
              assert.equal(state, 'completed');
              assert(fs.readFileSync(target).equals(stored), 'Downloaded document bytes changed');
              resolve({ filename, bytes: stored.length });
            } catch (error) { reject(error); }
          });
        } catch (error) { clearTimeout(timer); item.cancel(); reject(error); }
      });
    });
    const downloadURL = JSON.stringify(artifact.download_url);
    await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('#artifacts a')).find(link => link.getAttribute('href') === ${downloadURL}).click()`);
    downloads.push(await result);
  }
  const firstId = Object.keys(fixture.artifact_paths)[0];
  const secondId = Object.keys(fixture.artifact_paths)[1];
  await window.webContents.executeJavaScript(`(() => {
    document.querySelector('[data-rename-artifact="${firstId}"]').click();
    const form = document.querySelector('[data-artifact-rename-form="${firstId}"]');
    form.querySelector('input').value = '我定制的哲学讲解'; form.requestSubmit();
  })()`);
  let renamed;
  for (let i = 0; i < 50; i++) {
    const listed = await (await fetch(`${url}/api/projects/${fixture.project_id}/artifacts`)).json();
    renamed = listed.find(row => row.id === firstId);
    if (renamed?.download_filename === '我定制的哲学讲解.docx') break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(renamed.download_filename, '我定制的哲学讲解.docx');
  await window.webContents.executeJavaScript(`refreshArtifacts().then(() => {
    document.getElementById('artifactSort').value = 'format';
    document.getElementById('artifactSort').dispatchEvent(new Event('change'));
  })`);
  await window.webContents.executeJavaScript(`(() => {
    const button = document.querySelector('[data-delete-artifact="${secondId}"]'); button.click(); button.click();
  })()`);
  let deleted = false;
  for (let i = 0; i < 50; i++) {
    const listed = await (await fetch(`${url}/api/projects/${fixture.project_id}/artifacts`)).json();
    if (!listed.some(row => row.id === secondId)) { deleted = true; break; }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(deleted && !fs.existsSync(fixture.artifact_paths[secondId]));
  const report = { ok: true, backend: command, downloads, rendering, handoffDisplay: { verified: true, safe: !handoffView.unsafe },
    generationControls: { paused, resumed },
    management: { renamed: renamed.download_filename, deleted, sorting: 'format' } };
  fs.writeFileSync(path.join(root, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  app.quit();
}).catch(error => {
  backend?.kill();
  console.error(error.stack);
  fs.writeFileSync(path.join(root, 'report.json'), JSON.stringify({ ok: false, error: error.stack }));
  app.exit(1);
});
