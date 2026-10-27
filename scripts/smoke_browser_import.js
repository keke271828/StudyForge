const {app, BrowserWindow} = require('electron');
const {captureArticleScript, publicAddress, canonicalVideoUrl} = require('../desktop/browser_import');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const window = new BrowserWindow({show:false, webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
  try {
    const body = '文章完整正文和推导条件。'.repeat(100);
    const html = '<h1>测试文章</h1><article><p>'+body+'</p><img alt="E=mc^2"><p>末尾不可遗漏细节</p><script>window.previewOnly=true</script></article>';
    await window.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent(html));
    const captured = await window.webContents.executeJavaScript(captureArticleScript);
    const result = {fullBody:captured.html.includes(body), tailRetained:captured.html.includes('末尾不可遗漏细节'),
      formulaRetained:captured.html.includes('E=mc^2'), scriptRemoved:!captured.html.includes('<script'),
      isolated: await window.webContents.executeJavaScript('typeof require === "undefined" && typeof window.studyforgeDesktop === "undefined"'),
      publicOnly:publicAddress('https://zhuanlan.zhihu.com/p/718779138') && !publicAddress('http://127.0.0.1') && !publicAddress('file:///C:/Windows')};
    await window.webContents.executeJavaScript(`document.body.innerHTML='<h1>视频课程</h1><main><video></video><p>简介和无关文字</p></main><aside>推荐</aside><div id="comments">评论内容</div>'; Object.defineProperty(document.querySelector('video'),'currentSrc',{value:'https://example.org/lecture.mp4'});`);
    const video = await window.webContents.executeJavaScript(captureArticleScript);
    result.videoOnly = video.kind === 'video' && video.html === '' && video.video_url === 'https://example.org/lecture.mp4'
      && !JSON.stringify(video).includes('评论内容') && !JSON.stringify(video).includes('无关文字');
    result.bilibiliPart = canonicalVideoUrl('https://player.bilibili.com/player.html?bvid=BV13x41117TL&page=3')
      === 'https://www.bilibili.com/video/BV13x41117TL?p=3';
    await window.webContents.executeJavaScript(`document.body.innerHTML='<main><video></video></main>'; Object.defineProperty(document.querySelector('video'),'currentSrc',{value:'blob:https://example.org/test'});`);
    const dynamic = await window.webContents.executeJavaScript(captureArticleScript);
    result.dynamicVideo = dynamic.kind === 'video' && dynamic.html === '' && dynamic.needs_media_url === true;
    await window.webContents.executeJavaScript(`document.body.innerHTML='<article><iframe src="about:blank"></iframe><p>不是视频正文的介绍</p></article>'; Object.defineProperty(document.querySelector('iframe'),'src',{value:'https://player.bilibili.com/player.html?bvid=BV13x41117TL&page=2'});`);
    const embedded = await window.webContents.executeJavaScript(captureArticleScript);
    result.embeddedPlayer = embedded.kind === 'video' && embedded.html === '' && embedded.video_url.endsWith('?p=2');
    if (Object.values(result).some(value=>!value)) throw new Error(JSON.stringify(result));
    console.log(JSON.stringify(result));
  } finally {window.destroy();app.quit();}
}).catch(error=>{console.error(error);app.exit(1);});
