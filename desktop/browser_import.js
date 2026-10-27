const { BrowserWindow, Menu, dialog, session } = require('electron');

function canonicalVideoUrl(value) {
  try {
    const u = new URL(value), host = u.hostname.toLowerCase();
    if (!['https:', 'http:'].includes(u.protocol)) return null;
    if (host === 'b23.tv') return u.href;
    if (host === 'bilibili.com' || host.endsWith('.bilibili.com')) {
      const id = u.pathname.match(/\/video\/((?:BV|av)[a-z0-9]+)/i)?.[1]
        || u.searchParams.get('bvid') || (host === 'player.bilibili.com' && /^\d+$/.test(u.searchParams.get('aid') || '') ? 'av' + u.searchParams.get('aid') : null);
      if (!id || !/^(BV[a-z0-9]+|av\d+)$/i.test(id)) return null;
      const p = u.searchParams.get('p') || u.searchParams.get('page') || '1';
      return 'https://www.bilibili.com/video/' + id + '?p=' + (/^[1-9]\d*$/.test(p) ? p : '1');
    }
    if (host === 'youtu.be' && u.pathname !== '/') return u.href;
    if (['youtube.com','www.youtube.com','m.youtube.com','www.youtube-nocookie.com'].includes(host)) {
      const id = u.pathname.match(/^\/(embed|shorts|live)\/([\w-]+)/)?.[2] || u.searchParams.get('v');
      if (id) return 'https://www.youtube.com/watch?v=' + id;
    }
    if (['vimeo.com','www.vimeo.com','player.vimeo.com'].includes(host) && /\/\d+(\/|$)/.test(u.pathname)) return u.href;
    if (/\.(mp4|mov|mkv|webm|avi|m3u8|mpd|flv)$/i.test(u.pathname)) return u.href;
  } catch (_) {}
  return null;
}

const captureArticleScript = `(() => {
  const canonicalVideoUrl = ${canonicalVideoUrl.toString()};
  const title = document.querySelector('h1')?.textContent.trim() || document.title;
  const videoResult = (url, needsMedia = false) => ({kind: 'video', url: location.href, title,
    video_url: url, needs_media_url: needsMedia, html: ''});
  const known = canonicalVideoUrl(location.href);
  if (known) return videoResult(known);
  const scope = document.querySelector('main, article') || document;
  const players = [...scope.querySelectorAll('video')].filter(node => !node.closest('aside,nav,footer,.ad,.advertisement,[data-ad],.recommend,.comments,#comments'));
  players.sort((a,b) => {const x=a.getBoundingClientRect(), y=b.getBoundingClientRect(); return y.width*y.height - x.width*x.height;});
  if (players.length) {
    const player = players[0];
    const candidates = [player.currentSrc, player.src, ...[...player.querySelectorAll('source')].map(s => s.src)];
    const source = candidates.find(value => /^https?:/.test(value || ''));
    return source ? videoResult(canonicalVideoUrl(source) || source) : videoResult(location.href, true);
  }
  for (const frame of scope.querySelectorAll('iframe[src]')) {
    if (frame.closest('aside,nav,footer,.ad,.advertisement,.recommend,.comments,#comments')) continue;
    const embedded = canonicalVideoUrl(frame.src);
    if (embedded) return videoResult(embedded);
  }
  for (const meta of document.querySelectorAll('meta[property="og:video"],meta[property="og:video:url"],meta[property="og:video:secure_url"]')) {
    try {const target = new URL(meta.content, location.href); if (/^https?:$/.test(target.protocol)) return videoResult(canonicalVideoUrl(target.href) || target.href);} catch (_) {}
  }
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    const visit = value => {
      if (Array.isArray(value)) return value.map(visit).find(Boolean);
      if (!value || typeof value !== 'object') return null;
      if ([value['@type']].flat().includes('VideoObject')) {
        const target = value.contentUrl || value.embedUrl;
        if (typeof target === 'string') {try {const u = new URL(target,location.href); if (/^https?:$/.test(u.protocol)) return u.href;} catch (_) {}}
      }
      return visit(value['@graph']);
    };
    try {const target=visit(JSON.parse(script.textContent)); if(target) return videoResult(canonicalVideoUrl(target)||target);} catch (_) {}
  }
  const root = document.querySelector('.Post-RichTextContainer .RichText, article, .RichText.ztext, main');
  if (!root) throw new Error('页面还没有显示文章正文，请完成登录或验证后再导入');
  const copy = root.cloneNode(true);
  copy.querySelectorAll('script,style,nav,footer,iframe,form,button').forEach(node => node.remove());
  const text = copy.textContent.trim();
  if (text.length < 100) throw new Error('正文过短，可能尚未加载完整；请打开文章后重试');
  return {kind: 'article', url: location.href, title,
    html: copy.outerHTML};
})()`;

function publicAddress(value) {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password
      && !/^(localhost|127\.|0\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?$)/.test(host)
      && !host.endsWith('.local') && !host.endsWith('.localhost');
  } catch (_) { return false; }
}

function registerBrowserImporter(ipcMain, allowedOrigin, getParent) {
  let importing = false;
  ipcMain.handle('studyforge:import-browser-page', async (event, url) => {
    if (!event.senderFrame || event.senderFrame !== event.sender.mainFrame
      || new URL(event.senderFrame.url).origin !== allowedOrigin) throw new Error('无效的导入请求');
    if (typeof url !== 'string' || !publicAddress(url)) throw new Error('请输入公开的 HTTP/HTTPS 网址');
    if (importing) throw new Error('浏览器导入窗口已经打开，请先完成当前导入');
    const checked = await fetch(allowedOrigin + '/api/import/url/validate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url})
    });
    if (!checked.ok) throw new Error((await checked.json()).detail || '网址不可访问');
    importing = true;
    try {
      return await new Promise((resolve, reject) => {
        const remoteSession = session.fromPartition('persist:studyforge-browser-import');
        remoteSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
        remoteSession.setPermissionCheckHandler(() => false);
        const browser = new BrowserWindow({width: 1100, height: 820, parent: getParent(),
          title: '视频请先播放，再点击“导入视频内容”；文章点击“导入当前页面”',
          webPreferences: {nodeIntegration: false, contextIsolation: true, sandbox: true,
            session: remoteSession}});
        let finished = false;
        const mediaUrls = [];
        remoteSession.webRequest.onHeadersReceived({urls:['http://*/*','https://*/*']}, (details, callback) => {
          if (!browser.isDestroyed() && details.webContentsId === browser.webContents.id && publicAddress(details.url)
            && /\.(m3u8|mpd|mp4|webm)(\?|$)/i.test(details.url)
            && !/\/(ads?|advert)\//i.test(details.url) && !mediaUrls.includes(details.url)) mediaUrls.push(details.url);
          callback({});
        });
        async function importCurrent(videoOnly = false) {
          try {
            const page = await browser.webContents.executeJavaScript(captureArticleScript);
            if (!publicAddress(page.url)) throw new Error('只能导入公开网页或视频');
            if (videoOnly && page.kind !== 'video') throw new Error('尚未识别到视频，请打开具体视频页并开始播放');
            if (page.kind === 'video') {
              if (page.needs_media_url && mediaUrls.length) page.video_url = mediaUrls.find(u=>/\.(m3u8|mpd)(\?|$)/i.test(u)) || mediaUrls[0];
              if (!publicAddress(page.video_url)) throw new Error('未取得公开的视频地址，请播放视频后重试');
              // Only the current site/video's cookies are used for the download.
              // No other browser accounts, cookies or page prose are exported.
              const collected = (await Promise.all([...new Set([page.url,page.video_url])].map(u=>remoteSession.cookies.get({url:u})))).flat();
              const unique = new Map(collected.map(c=>[c.domain+'|'+c.path+'|'+c.name,c]));
              page.cookies = [...unique.values()].slice(0,200).map(({domain,path,name,value,secure,httpOnly,expirationDate})=>({domain,path,name,value,secure,httpOnly,expirationDate}));
              delete page.needs_media_url;
            } else if (page.html.length > 8000000) throw new Error('页面内容过大，请保存为本地文件导入');
            finished = true; resolve(page); browser.close();
          } catch (error) {
            await dialog.showMessageBox(browser, {type: 'info', message: error.message,
              detail: '视频需完成登录或验证并确认可播放，再点击“导入视频内容”。文章需显示完整正文，再点击“导入当前页面”。'});
          }
        }
        browser.setMenu(Menu.buildFromTemplate([
          {label: '导入视频内容', click: () => importCurrent(true)},
          {label: '导入当前页面', click: () => importCurrent()},
          {label: '刷新页面', role: 'reload'},
          {label: '取消导入', click: () => browser.close()}
        ]));
        browser.webContents.on('page-title-updated', e => e.preventDefault());
        browser.webContents.on('will-navigate', (e, target) => {if (!publicAddress(target)) e.preventDefault();});
        browser.webContents.on('will-redirect', (e, target) => {if (!publicAddress(target)) e.preventDefault();});
        browser.webContents.setWindowOpenHandler(({url: target}) => {
          if (publicAddress(target)) browser.loadURL(target).catch(() => {});
          return {action: 'deny'};
        });
        browser.on('closed', () => {remoteSession.webRequest.onHeadersReceived(null); if (!finished) resolve(null);});
        // Some sites send 403 while still showing a login or verification page.
        browser.loadURL(url).catch(error => {
          if (error.code !== 'ERR_ABORTED' && !browser.isDestroyed())
            dialog.showMessageBox(browser, {type: 'info', message: '页面暂时未加载成功', detail: '可尝试顶部“刷新页面”，或上传本地视频、PDF、HTML 后导入。'});
        });
      });
    } finally { importing = false; }
  });
}

module.exports = { registerBrowserImporter, captureArticleScript, publicAddress, canonicalVideoUrl };
