/* Read only the requested video's public metadata with Chromium networking. */
const {app, BrowserWindow, session} = require('electron');
const fs = require('node:fs'), path = require('node:path');
const output = process.env.STUDYFORGE_VIDEO_PROBE_DIR;
const target = process.env.STUDYFORGE_LIVE_URL || 'https://www.bilibili.com/video/BV1rH4y1N7BW/?p=2';
const requestedPage = Number(new URL(target).searchParams.get('p') || '1');
if (new URL(target).hostname !== 'www.bilibili.com') throw Error('This diagnostic reads public Bilibili video pages only');
if (!output) throw Error('STUDYFORGE_VIDEO_PROBE_DIR is required');
fs.mkdirSync(output, {recursive:true});
app.setPath('userData', path.join(output, 'browser-profile'));
app.disableHardwareAcceleration();
app.on('window-all-closed', ()=>{});
app.whenReady().then(async ()=>{
  const report={url:target, success:false};
  let win;
  try {
    const remote=session.fromPartition('video-ab-probe');
    remote.setUserAgent(remote.getUserAgent().replace(/\sElectron\/[^\s]+/g,''));
    win=new BrowserWindow({show:false,webPreferences:{session:remote,contextIsolation:true,sandbox:true,backgroundThrottling:false}});
    try {
      const dom=new Promise(resolve=>win.webContents.once('dom-ready',resolve));
      await Promise.race([win.loadURL(report.url),dom,new Promise((_,reject)=>setTimeout(()=>reject(Error('网页加载超过30秒')),30000))]);
      if(win.webContents.isLoading())win.webContents.stop();
      report.page=await win.webContents.executeJavaScript(`({title:document.title,text_length:document.body?.innerText.length||0,video_duration:document.querySelector('video')?.duration||null})`);
    }catch(error){report.page_error=error.message;}
    const identity=new URL(target).pathname.match(/\/video\/(BV[a-z0-9]+)/i)?.[1];
    const initial=await Promise.race([win.webContents.executeJavaScript(`(()=>{const s=window.__INITIAL_STATE__||{};const v=s.videoData||{};return {title:v.title,cid:s.cid||v.cid,pages:(v.pages||[]).map(p=>({cid:p.cid,page:p.page,part:p.part,duration:p.duration}))};})()`),new Promise(resolve=>setTimeout(()=>resolve(null),3000))]);
    report.initial_state=initial;
    report.playback=await win.webContents.executeJavaScript(`(()=>{const p=window.__playinfo__||{};const d=p.data||{};return {code:p.code,message:p.message,timelength:d.timelength,quality:d.quality,preview:!!d.is_preview,video:(d.dash?.video||[]).map(v=>({id:v.id,height:v.height,codecs:v.codecs,host:new URL(v.baseUrl||v.base_url,location.href).hostname})),audio_count:(d.dash?.audio||[]).length,progressive_count:(d.durl||[]).length};})()`);
    if(initial?.pages?.some(p=>p.page===requestedPage)){
      report.selected_page=initial.pages.find(p=>p.page===requestedPage);
      report.success=initial.cid===report.selected_page.cid;return;
    }
    const endpoint='https://api.bilibili.com/x/web-interface/view?bvid='+identity;
    const result=await win.webContents.executeJavaScript(`(async()=>{const r=await fetch(${JSON.stringify(endpoint)}, {credentials:'include',signal:AbortSignal.timeout(20000)});return {status:r.status,raw:r.ok?await r.json():null};})()`);
    report.api_status=result.status;
    if(result.raw){
      const raw=result.raw,data=raw.data||{};
      report.metadata={code:raw.code,message:raw.message,title:data.title,pages:(data.pages||[]).map(p=>({cid:p.cid,page:p.page,part:p.part,duration:p.duration}))};
      report.selected_page=report.metadata.pages.find(p=>p.page===requestedPage);
      report.success=raw.code===0 && !!report.selected_page;
    }
    if(!report.success && report.page)report.initial_state=await win.webContents.executeJavaScript(`(()=>{const s=window.__INITIAL_STATE__||{};const v=s.videoData||{};return {title:v.title,cid:s.cid||v.cid,pages:(v.pages||[]).map(p=>({cid:p.cid,page:p.page,part:p.part,duration:p.duration}))};})()`);
  }catch(error){report.error=error.message;}
  finally{fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));app.exit(0);}
});
