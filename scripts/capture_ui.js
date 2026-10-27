const { app, BrowserWindow } = require('electron');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs');

app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const window = new BrowserWindow({ show: process.env.STUDYFORGE_CAPTURE_VISIBLE === '1',
    width: Number(process.env.STUDYFORGE_CAPTURE_WIDTH) || 1440,
    height: Number(process.env.STUDYFORGE_CAPTURE_HEIGHT) || 900,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  await window.loadURL(process.env.STUDYFORGE_TEST_URL || 'http://127.0.0.1:8766');
  await new Promise(resolve => setTimeout(resolve, 1500));
  if (process.env.STUDYFORGE_CAPTURE_PROJECT) {
    await window.webContents.executeJavaScript(`(() => {
      const project = [...document.querySelectorAll('.navigation-project')]
        .find(item => item.querySelector('.navigation-label')?.textContent === ${JSON.stringify(process.env.STUDYFORGE_CAPTURE_PROJECT)});
      if (!project) throw new Error('截图项目未找到');
      project.querySelector('.navigation-open').click();
    })()`);
    await new Promise(resolve => setTimeout(resolve, 600));
  }
  if (process.env.STUDYFORGE_CAPTURE_VIEW) {
    await window.webContents.executeJavaScript(`(() => {
      const name = ${JSON.stringify(process.env.STUDYFORGE_CAPTURE_VIEW)};
      const view = [...document.querySelectorAll('[data-view]')]
        .find(item => item.dataset.view === name);
      if (!view) throw new Error('截图页面未找到');
      view.click();
    })()`);
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  if (process.env.STUDYFORGE_CAPTURE_ADVANCED === '1') {
    await window.webContents.executeJavaScript("document.querySelector('.advanced-generation').open = true");
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  const screenshot = await window.webContents.capturePage();
  const target = process.env.STUDYFORGE_SCREENSHOT_PATH || path.join(os.tmpdir(), 'studyforge-ui-smoke.png');
  fs.writeFileSync(target, screenshot.toPNG());
  console.log(target);
  window.destroy();
  app.quit();
}).catch(error => { console.error(error); app.exit(1); });
