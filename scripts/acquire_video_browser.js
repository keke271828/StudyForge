/* Acquire an ordinary public Bilibili playback in an isolated browser session.
 * No cookies/account stores are inspected or exported. Signed asset URLs stay
 * in memory; reports contain only episode identity, duration and local paths.
 */
const {app,BrowserWindow,session}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const {Readable,Transform}=require('node:stream');
const {pipeline}=require('node:stream/promises');
const target=new URL(process.env.STUDYFORGE_LIVE_URL||'');
const output=path.resolve(process.env.STUDYFORGE_VIDEO_PROBE_DIR||'');
const workspace=path.resolve(__dirname,'..','build');
if(!output.startsWith(workspace+path.sep))throw Error('Acquisition output must be inside workspace build');
const identity=target.pathname.match(/^\/video\/(BV[a-z0-9]+)\/?$/i)?.[1];
const page=Number(target.searchParams.get('p')||'1');
if(target.hostname!=='www.bilibili.com'||target.protocol!=='https:'||!identity||!Number.isInteger(page)||page<1)
  throw Error('Only the requested public Bilibili video episode is supported');
fs.mkdirSync(output,{recursive:true});app.setPath('userData',path.join(output,'profile'));
app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
const report={url:target.href,page,status:'acquiring',files:[]};
const started=Date.now();
function save(){report.elapsed_seconds=(Date.now()-started)/1000;fs.writeFileSync(path.join(output,'acquired.json'),JSON.stringify(report,null,2));}
function bounded(p,ms=25000){return Promise.race([p,new Promise((_,reject)=>setTimeout(()=>reject(Error('读取播放信息超时')),ms))]);}
function publicAsset(value){
  const url=new URL(value.startsWith('//')?'https:'+value:value);
  if(url.protocol!=='https:'||url.username||url.password||
    !['bilivideo.com','bilivideo.cn'].some(host=>url.hostname===host||url.hostname.endsWith('.'+host)))
    throw Error('播放资源不是已知的公开视频 CDN');
  return url.href;
}
app.whenReady().then(async()=>{
  let win;
  try{
    const remote=session.fromPartition('video-ab-acquire');
    remote.setUserAgent(remote.getUserAgent().replace(/\sElectron\/[^\s]+/g,''));
    remote.setPermissionRequestHandler((_w,_p,cb)=>cb(false));
    win=new BrowserWindow({show:false,webPreferences:{session:remote,nodeIntegration:false,contextIsolation:true,sandbox:true,backgroundThrottling:false}});
    const dom=new Promise(resolve=>win.webContents.once('dom-ready',resolve));
    await bounded(Promise.race([win.loadURL(target.href),dom]),30000);
    // Electron queues executeJavaScript until the page stops loading. Optional
    // ads/recommendations can leave that state pending after the HTML is ready.
    if(win.webContents.isLoading())win.webContents.stop();
    const initial=await bounded(win.webContents.executeJavaScript(`(()=>{const s=window.__INITIAL_STATE__||{};return {cid:s.cid||s.videoData?.cid,data:s.videoData,play:window.__playinfo__};})()`),5000);
    let data=initial.data;
    if(!data?.pages?.length){
      const endpoint='https://api.bilibili.com/x/web-interface/view?bvid='+identity;
      const raw=await bounded(win.webContents.executeJavaScript(`(async()=>{const r=await fetch(${JSON.stringify(endpoint)},{credentials:'include',signal:AbortSignal.timeout(20000)});if(!r.ok)throw Error('公开视频信息请求被拒绝');return await r.json();})()`));
      if(raw.code!==0)throw Error('站点没有返回公开视频信息');
      data=raw.data;
    }
    const episode=data.pages.find(item=>item.page===page);
    if(!episode||!episode.cid||!episode.duration)throw Error('无法确认请求的具体分集');
    report.title=episode.part;report.collection_title=data.title;
    report.cid=episode.cid;report.duration_seconds=episode.duration;save();
    let play=initial.cid===episode.cid?initial.play:null;
    if(!play?.data){
      const endpoint='https://api.bilibili.com/x/player/playurl?bvid='+identity+'&cid='+episode.cid+'&qn=80&fnval=4048&fnver=0&fourk=0';
      play=await bounded(win.webContents.executeJavaScript(`(async()=>{const r=await fetch(${JSON.stringify(endpoint)},{credentials:'include',signal:AbortSignal.timeout(20000)});if(!r.ok)throw Error('公开视频音画请求被拒绝');return await r.json();})()`));
    }
    const stream=play.data;
    if(play.code!==0||!stream||stream.is_preview||stream.is_drm||stream.drm_tech_type)
      throw Error('站点没有开放完整普通播放；不会绕过登录、付费或受保护内容');
    if(Math.abs((stream.timelength||0)/1000-episode.duration)>5)
      throw Error('返回的音画时长与完整分集不符，可能是预览片段');
    const videos=(stream.dash?.video||[]).filter(v=>v.height<=1080&&!v.drm_info);
    videos.sort((a,b)=>b.height-a.height||(a.codecs?.startsWith('avc')?-1:1));
    const audios=(stream.dash?.audio||[]).filter(a=>!a.drm_info).sort((a,b)=>(b.bandwidth||0)-(a.bandwidth||0));
    const resources=videos.length&&audios.length
      ?[{kind:'video',name:'video.m4s',item:videos[0]},{kind:'audio',name:'audio.m4s',item:audios[0]}]
      :(stream.durl?.length===1?[{kind:'combined',name:'playback.mp4',item:stream.durl[0]}]:[]);
    if(!resources.length)throw Error('未取得完整、可合并的公开视频音轨与画面');
    report.height=videos[0]?.height;report.stage='下载完整音轨与画面';save();
    let total=0;
    for(const resource of resources){
      const url=publicAsset(resource.item.baseUrl||resource.item.base_url||resource.item.url);
      const destination=path.join(output,resource.name);
      const response=await remote.fetch(url,{headers:{Referer:'https://www.bilibili.com/'},redirect:'error',signal:AbortSignal.timeout(600000)});
      if(!response.ok||!response.body)throw Error('公开视频资源下载被拒绝');
      const meter=new Transform({transform(chunk,_enc,cb){total+=chunk.length;if(total>2*1024**3)return cb(Error('音画总大小超过 2 GB'));cb(null,chunk);}});
      await pipeline(Readable.fromWeb(response.body),meter,fs.createWriteStream(destination,{flags:'wx'}));
      report.files.push({kind:resource.kind,path:destination,bytes:fs.statSync(destination).size});save();
    }
    report.status='downloaded';
  }catch(error){
    report.status='failed';
    // Remote errors can contain signed URLs. Never write those into reports.
    report.error=String(error.message||'读取失败').replace(/https?:\/\/\S+/g,'[远程地址]');
    for(const name of ['video.m4s','audio.m4s','playback.mp4'])fs.rmSync(path.join(output,name),{force:true});
    report.files=[];
  }finally{save();console.log(JSON.stringify(report));app.exit(report.status==='downloaded'?0:2);}
});
