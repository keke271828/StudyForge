const fs=require('node:fs');
const fsp=fs.promises;
const path=require('node:path');
const crypto=require('node:crypto');
const {desktopCaller}=require('./lifecycle');
const {createGitHubReleaseClient,sourceKey,officialReleasePage}=require('./github_releases');

const defaults={feed_url:'',auto_check:true,auto_download:false,interval_hours:24};
function versionParts(value){
  if(typeof value!=='string'||!/^\d{1,6}\.\d{1,6}\.\d{1,6}$/.test(value))throw new Error('更新版本号必须是稳定版 major.minor.patch');
  return value.split('.').map(Number);
}
function compareVersions(a,b){const x=versionParts(a),y=versionParts(b);for(let i=0;i<3;i++)if(x[i]!==y[i])return x[i]>y[i]?1:-1;return 0;}
function feedUrl(value,allowTestUrls=false){
  if(value==='')return '';
  if(typeof value!=='string'||value.length>1500)throw new Error('更新地址格式不正确，请从发布者提供的说明中重新复制');
  let url;try{url=new URL(value.trim());}catch(_){throw new Error('请填写发布者提供的 HTTPS 更新地址');}
  if(url.username||url.password||url.search||url.hash)throw new Error('请填写完整更新目录地址，不要附带密码、问号参数或 # 后的内容');
  if(url.protocol!=='https:'&&!(allowTestUrls&&url.protocol==='http:'&&['127.0.0.1','localhost'].includes(url.hostname)))
    throw new Error('更新源必须使用 HTTPS');
  if(/\.(?:exe|ya?ml)$/i.test(url.pathname))throw new Error('这里需要更新目录的地址，不是 .exe 安装包或 latest.yml 文件的下载地址');
  url.pathname=url.pathname.replace(/\/*$/,'/');return url.href;
}
function preferences(value,allowTestUrls=false){
  if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('更新设置无效');
  const keys=Object.keys(defaults);if(Object.keys(value).some(key=>!keys.includes(key)))throw new Error('未知的更新设置');
  const result={...defaults,...value};result.feed_url=feedUrl(result.feed_url,allowTestUrls);
  if(typeof result.auto_check!=='boolean'||typeof result.auto_download!=='boolean')throw new Error('更新开关必须是布尔值');
  if(!Number.isInteger(result.interval_hours)||result.interval_hours<1||result.interval_hours>168)throw new Error('检查间隔应为 1 至 168 小时');
  return result;
}
function candidateInfo(info,base,allowTestUrls=false){
  versionParts(info?.version);
  const files=info.files;if(!Array.isArray(files)||files.length!==1||info.packages)throw new Error('只接受单个完整 NSIS 安装包');
  const file=files[0];let url;try{url=new URL(file.url,base);}catch(_){throw new Error('安装包地址无效');}
  if(url.protocol!=='https:'&&!(allowTestUrls&&url.protocol==='http:'&&['127.0.0.1','localhost'].includes(url.hostname)))throw new Error('安装包必须使用 HTTPS');
  if(url.username||url.password||url.hash)throw new Error('安装包地址含不允许的内容');
  if(decodeURIComponent(path.posix.basename(url.pathname))!==`StudyForge-Setup-${info.version}.exe`)throw new Error('更新文件名与 StudyForge 版本不匹配');
  if(typeof file.sha512!=='string'||!/^[A-Za-z0-9+/]{86}==$/.test(file.sha512)||Buffer.from(file.sha512,'base64').length!==64)throw new Error('安装包缺少有效的 SHA-512 校验值');
  if(!Number.isSafeInteger(file.size)||file.size<=0||file.size>4*1024**3)throw new Error('安装包大小无效');
  const notes=Array.isArray(info.releaseNotes)?info.releaseNotes.map(x=>x.note||'').join('\n\n'):info.releaseNotes||'';
  return {version:info.version,size:file.size,sha512:file.sha512,notes:String(notes).slice(0,12000),
    feed_url:base,isAdminRightsRequired:file.isAdminRightsRequired===true};
}
async function sha512(file){const hash=crypto.createHash('sha512');for await(const bytes of fs.createReadStream(file))hash.update(bytes);return hash.digest('base64');}
function readJson(file,fallback){try{return JSON.parse(fs.readFileSync(file,'utf8'));}catch(_){return fallback;}}
function atomicJson(file,value){fs.mkdirSync(path.dirname(file),{recursive:true});const temporary=file+'.tmp';
  fs.writeFileSync(temporary,JSON.stringify(value,null,2),{mode:0o600});fs.renameSync(temporary,file);}

function createUpdateManager({currentVersion,packaged,storageDirectory,publishers=[],initialFeed='',createUpdater,
  requestQuit,notify=()=>{},launchInstaller,allowTestUrls=false,releaseClient=createGitHubReleaseClient()}){
  versionParts(currentVersion);
  const settingsFile=path.join(storageDirectory,'update-preferences.json'),historyFile=path.join(storageDirectory,'update-history.json');
  const cache=path.join(storageDirectory,'update-installers');fs.mkdirSync(cache,{recursive:true});
  let config,loadError='';try{config=preferences({...defaults,feed_url:initialFeed,...readJson(settingsFile,{})},allowTestUrls);}
  catch(error){config={...defaults};loadError=error.message;}
  let history=readJson(historyFile,{releases:[],pending:null});
  if(!history||!Array.isArray(history.releases))history={releases:[],pending:null};
  history.releases=history.releases.filter(x=>{try{return x&&versionParts(x.version)&&
    (x.provider==='github'?/^[a-f0-9]{64}$/.test(x.sha256):typeof x.sha512==='string')&&Number.isSafeInteger(x.size);}catch(_){return false;}});
  const trust=publishers.filter(x=>typeof x==='string'&&x.trim()).map(x=>x.trim());
  let updater,checkPromise,downloadPromise,installPromise,timer,bootTimer,downloadController,checkController,disposed=false,checked=false;
  const github=()=>!config.feed_url;
  const activeSource=()=>config.feed_url||sourceKey;
  const eligible=record=>compareVersions(record.version,currentVersion)>0||
    (!packaged&&record.provider==='github'&&compareVersions(record.version,currentVersion)===0);
  let state={status:loadError?'error':config.feed_url&&!packaged?'development':'idle',error:loadError,
    current_version:currentVersion,last_checked:null,progress:null,candidate:null};
  if(history.pending){
    if(history.pending.target===currentVersion){history.last_success={...history.pending,completed_at:new Date().toISOString()};history.pending=null;atomicJson(historyFile,history);}
    else if(history.pending.from===currentVersion){state.error='上次更新未切换到目标版本，可重新检查或安装；学习数据保留。';history.pending=null;atomicJson(historyFile,history);}
  }
  const localFile=record=>path.join(cache,`StudyForge-Setup-${record.version}.exe`);
  const previous=()=>history.releases.filter(x=>x.provider!=='github'&&compareVersions(x.version,currentVersion)<0&&fs.existsSync(localFile(x))).sort((a,b)=>compareVersions(b.version,a.version))[0]||null;
  const downloaded=()=>history.releases.filter(x=>eligible(x)&&x.feed_url===activeSource()&&fs.existsSync(localFile(x))).sort((a,b)=>compareVersions(b.version,a.version))[0]||null;
  function snapshot(){return {...state,settings:{...config},packaged,signature_configured:trust.length>0,
    provider:github()?'github':'generic',release_url:officialReleasePage(state.candidate?.release_url),
    can_check:github()||packaged,can_cancel:github()&&state.status==='downloading',
    manual_install:github()||!packaged||!trust.length,
    can_reveal_download:state.status==='downloaded'&&Boolean(downloaded()),
    can_install:!github()&&packaged&&trust.length>0&&state.status==='downloaded',rollback_version:previous()?.version||null,
    can_download:(github()||packaged)&&checked&&Boolean(state.candidate)&&eligible(state.candidate)&&!busy()&&state.status!=='downloaded',
    can_rollback:packaged&&trust.length>0&&Boolean(previous()),recovery:history.last_success?.backup||null};}
  function emit(patch){if(disposed)return;state={...state,...patch};notify(snapshot());}
  function failure(error){emit({status:'error',error:String(error.message||error).slice(0,600),progress:null,retry_at:error.retry_at||null});}
  function busy(){return ['checking','downloading','installing'].includes(state.status);}
  function requireInstalled(){if(!packaged)throw new Error('当前是从项目文件夹打开的测试版。可以保存更新设置；自动下载安装需要正式安装版。');}
  function requireSource(){if(!config.feed_url)throw new Error('还没有设置更新地址。有发布者提供的 HTTPS 地址后，再填入启用。');}
  function ensureUpdater(){
    if(updater)return updater;
    updater=createUpdater(config.feed_url?{provider:'generic',url:config.feed_url,useMultipleRangeRequest:false}:null);
    updater.autoDownload=false;updater.autoInstallOnAppQuit=false;updater.allowDowngrade=false;updater.allowPrerelease=false;
    updater.disableWebInstaller=true;
    updater.on('error',failure);
    updater.on('download-progress',progress=>{if(state.status==='downloading')emit({progress:{percent:Math.max(0,Math.min(100,Number(progress.percent)||0)),
      transferred:Number(progress.transferred)||0,total:Number(progress.total)||0,bytes_per_second:Number(progress.bytesPerSecond)||0}});});
    return updater;
  }
  async function verify(record){
    versionParts(record.version);const file=localFile(record),stat=await fsp.lstat(file);
    if(!stat.isFile()||stat.isSymbolicLink()||stat.size!==record.size||await sha512(file)!==record.sha512)throw new Error('下载的安装包不完整，或内容发生变化。请重新下载。');
    if(!trust.length)throw new Error('尚未设置发布者身份，软件无法确认这个安装包来自谁，因此没有自动安装');
    const result=await ensureUpdater().verifyUpdateCodeSignature(trust,file);
    if(result!==null)throw new Error('安装包发布者签名核验失败：'+String(result).slice(0,200));
    return file;
  }
  async function revealDownload(){
    const record=downloaded();if(!record)throw new Error('还没有下载完成的安装包，请先检查并下载。');
    try{
      const file=localFile(record),stat=await fsp.lstat(file),hash=crypto.createHash(record.provider==='github'?'sha256':'sha512');
      if(!stat.isFile()||stat.isSymbolicLink()||stat.size!==record.size)throw new Error('保存的安装包已不完整，请重新下载。');
      for await(const bytes of fs.createReadStream(file))hash.update(bytes);
      if(hash.digest(record.provider==='github'?'hex':'base64')!==(record.provider==='github'?record.sha256:record.sha512))
        throw new Error('保存的安装包内容发生变化，请重新下载。');
      return file;
    }catch(error){failure(error);throw error;}
  }
  async function download(){
    if(!github()){requireInstalled();requireSource();}if(downloadPromise)return downloadPromise;
    if(state.status==='installing'||checkPromise)throw new Error('请等待当前更新操作完成');
    if(!checked)throw new Error('请先检查更新，再下载当前发布的安装包');
    const info=state.candidate;if(!info||!eligible(info))throw new Error('请先检查并选择可下载的正式版本');
    downloadPromise=(async()=>{
      emit({status:'downloading',error:'',progress:{percent:0,transferred:0,total:info.size,bytes_per_second:0}});
      try{
        if(info.provider==='github'){
          downloadController=new AbortController();await releaseClient.download(info,localFile(info),{signal:downloadController.signal,
            onProgress:progress=>emit({progress})});
        }else{
          const files=await ensureUpdater().downloadUpdate();if(files.length!==1)throw new Error('下载的安装包数量不符');
          const stat=await fsp.lstat(files[0]);if(!stat.isFile()||stat.isSymbolicLink()||stat.size!==info.size||await sha512(files[0])!==info.sha512)throw new Error('下载内容与发布校验值不符');
          const destination=localFile(info),temporary=destination+'.part';await fsp.copyFile(files[0],temporary);await fsp.rename(temporary,destination);
          // Signature verification remains mandatory before automatic execution.
          if(trust.length)await verify(info);
        }
        history.releases=history.releases.filter(x=>x.version!==info.version).concat(info);atomicJson(historyFile,history);
        emit({status:'downloaded',progress:{percent:100,transferred:info.size,total:info.size,bytes_per_second:0}});return snapshot();
      }catch(error){if(downloadController?.signal.aborted){emit({status:'cancelled',error:'',progress:null});return snapshot();}
        failure(error);throw error;}
      finally{downloadPromise=null;downloadController=null;}
    })();return downloadPromise;
  }
  async function check(){
    if(!github()){requireInstalled();requireSource();}if(checkPromise)return checkPromise;if(downloadPromise||state.status==='installing')return snapshot();
    if(state.retry_at&&new Date(state.retry_at).getTime()>Date.now())throw new Error('GitHub 检查次数暂时受限，请在 '+new Date(state.retry_at).toLocaleString('zh-CN')+' 后重试，或打开发布页面。');
    checkPromise=(async()=>{
      checked=false;emit({status:'checking',error:'',progress:null,retry_at:null});
      try{
        let info;if(github()){checkController=new AbortController();info=await releaseClient.check({signal:checkController.signal});}
        else{const result=await ensureUpdater().checkForUpdates();if(!result?.updateInfo)throw new Error('更新源未返回有效版本信息');
          info=candidateInfo(result.updateInfo,config.feed_url,allowTestUrls);}
        checked=true;
        if(!eligible(info))emit({status:github()&&compareVersions(info.version,currentVersion)<0?'ahead':'current',last_checked:new Date().toISOString(),candidate:github()?info:null});
        else{
          const saved=downloaded();emit({status:saved?.version===info.version&&(info.provider==='github'?saved.sha256===info.sha256:saved.sha512===info.sha512)?'downloaded':
            compareVersions(info.version,currentVersion)===0?'current':'available',
            last_checked:new Date().toISOString(),candidate:info});
        }
      }catch(error){failure(error);throw error;}
      finally{checkPromise=null;checkController=null;}
      if(config.auto_download&&state.status==='available')return download();return snapshot();
    })();return checkPromise;
  }
  function schedule(){
    clearInterval(timer);clearTimeout(bootTimer);
    if(disposed||(!github()&&!packaged)||!config.auto_check)return;
    bootTimer=setTimeout(()=>check().catch(()=>{}),20000);bootTimer.unref();
    timer=setInterval(()=>check().catch(()=>{}),config.interval_hours*3600000);timer.unref();
  }
  function save(value){
    if(busy())throw new Error('请等待更新操作完成后再修改更新源');
    const next=preferences(value,allowTestUrls);
    const changed=next.feed_url!==config.feed_url;
    if(changed){updater?.removeAllListeners();updater=null;state.candidate=null;state.retry_at=null;checked=false;}
    atomicJson(settingsFile,next);config=next;
    const saved=downloaded();emit({status:!github()&&!packaged?'development':saved?'downloaded':changed?'idle':state.status,
      error:'',candidate:saved||state.candidate});
    schedule();return snapshot();
  }
  async function install(rollback=false){
    if(installPromise)return installPromise;
    requireInstalled();if(!rollback&&github())throw new Error('GitHub 安装包请在下载完成后打开所在文件夹，手动运行安装器；自动安装尚未启用。');
    if(busy())throw new Error('更新操作正在进行');
    const record=rollback?previous():downloaded();if(!record)throw new Error(rollback?'暂无可恢复安装包':'尚无已下载的新版本');
    installPromise=(async()=>{
    // Validate before closing the app so a bad cache cannot interrupt learning.
    const file=await verify(record);emit({status:'installing',error:'',candidate:record});
    requestQuit({from:currentVersion,target:record.version,rollback,
      afterStop:async receipt=>{
        try{
          if(!receipt?.backup?.id)throw new Error('尚未确认学习记录已备份，这次安装已取消；可以重新检查更新后再试');
          await verify(record); // Recheck immediately before executing the cached binary.
          history.pending={from:currentVersion,target:record.version,rollback,backup:receipt?.backup||null,started_at:new Date().toISOString()};
          atomicJson(historyFile,history);await launchInstaller(file,record.isAdminRightsRequired);
        }catch(error){history.pending=null;atomicJson(historyFile,history);failure(error);throw error;}
      },onFailure:failure});
    return snapshot();
    })().catch(error=>{failure(error);throw error;}).finally(()=>{installPromise=null;});return installPromise;
  }
  const saved=downloaded();if(saved&&!loadError)state={...state,status:'downloaded',candidate:saved};
  return {snapshot,save,check,download,install,revealDownload,cancelDownload(){downloadController?.abort();return snapshot();},
    start:schedule,dispose(){disposed=true;clearInterval(timer);clearTimeout(bootTimer);downloadController?.abort();checkController?.abort();},
    recoveryDirectory:()=>cache};
}

function registerUpdateHandlers(ipcMain,allowedOrigin,getWindow,manager,openRecovery,confirmRollback,
  openRelease=()=>{},revealFile=()=>{}){
  for(const [channel,callback] of [
    ['studyforge:update-status',()=>manager.snapshot()],['studyforge:update-save',value=>manager.save(value)],
    ['studyforge:update-check',()=>manager.check()],['studyforge:update-download',()=>manager.download()],
    ['studyforge:update-install',()=>manager.install()],
    ['studyforge:update-cancel',()=>manager.cancelDownload()],
    ['studyforge:update-release',()=>openRelease(manager.snapshot().release_url)],
    ['studyforge:update-reveal',async()=>{await revealFile(await manager.revealDownload());return manager.snapshot();}],
    ['studyforge:update-rollback',async()=>await confirmRollback()?manager.install(true):manager.snapshot()],
    ['studyforge:update-recovery',()=>openRecovery()]
  ])ipcMain.handle(channel,(event,value)=>{desktopCaller(event,allowedOrigin,getWindow);return callback(value);});
}
module.exports={createUpdateManager,registerUpdateHandlers,preferences,feedUrl,candidateInfo,compareVersions,sha512};
