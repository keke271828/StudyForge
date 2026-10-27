const CHANNEL = 'studyforge:copy-text';

function registerClipboardHandler(ipcMain, clipboard, allowedOrigin) {
  ipcMain.handle(CHANNEL, async (event, value) => {
    const frame = event.senderFrame;
    if (!frame || frame !== event.sender.mainFrame || new URL(frame.url).origin !== allowedOrigin) {
      throw new Error('只允许 StudyForge 窗口复制内容');
    }
    if (typeof value !== 'string' || value.length > 100000) {
      throw new Error('复制内容无效或过长');
    }
    await clipboard.writeText(value);
  });
}

module.exports = { registerClipboardHandler };
