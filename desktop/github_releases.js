// Public release discovery and bounded-memory downloads. This never runs an installer.
const fs=require('node:fs');
const fsp=fs.promises;
const path=require('node:path');
const crypto=require('node:crypto');
const {Readable,Transform}=require('node:stream');
const {pipeline}=require('node:stream/promises');

const repository='keke271828/StudyForge';
const releasePage=`https://github.com/${repository}/releases/latest`;
const releaseApi=`https://api.github.com/repos/${repository}/releases/latest`;
const sourceKey=`https://github.com/${repository}/releases`;
const maxInstallerSize=4*1024**3;
function officialReleasePage(value){
  return typeof value==='string'&&new RegExp('^https://github\\.com/'+repository+'/releases/tag/v?\\d{1,6}\\.\\d{1,6}\\.\\d{1,6}$').test(value)?value:releasePage;
}

function releaseInfo(value){
  const version=/^v?(\d{1,6}\.\d{1,6}\.\d{1,6})$/.exec(value?.tag_name||'')?.[1];
  if(!version||value.draft!==false||value.prerelease!==false)throw new Error('GitHub 尚未提供可用的正式版本，请到发布页面查看。');
  const tag=value.tag_name,name=`StudyForge-Setup-${version}.exe`;
  const expectedPage=`https://github.com/${repository}/releases/tag/${tag}`;
  if(value.html_url!==expectedPage)throw new Error('版本信息不属于 StudyForge 官方发布页。');
  const assets=Array.isArray(value.assets)?value.assets:[];
  const matches=assets.filter(x=>x.name===name&&x.state==='uploaded');
  if(matches.length!==1)throw new Error('这个版本的 Windows 安装包还没有上传完整，请稍后重试或查看发布页面。');
  const asset=matches[0],url=`https://github.com/${repository}/releases/download/${tag}/${name}`;
  if(asset.browser_download_url!==url||!Number.isSafeInteger(asset.size)||asset.size<=0||asset.size>maxInstallerSize)
    throw new Error('发布的安装包地址或大小不正确，请查看官方发布页面。');
  const sha256=/^sha256:([a-f0-9]{64})$/i.exec(asset.digest||'')?.[1].toLowerCase();
  if(!sha256)throw new Error('发布的安装包缺少完整性校验信息，暂不能在软件内下载；可查看官方发布页面。');
  const assetId=Number.isSafeInteger(asset.id)&&asset.id>0?asset.id:null;
  const assetApi=assetId?`https://api.github.com/repos/${repository}/releases/assets/${assetId}`:null;
  if(asset.url&&asset.url!==assetApi)throw new Error('安装包附件不属于 StudyForge 官方仓库。');
  return {provider:'github',version,size:asset.size,sha256,url,feed_url:sourceKey,
    asset_id:assetId,asset_api_url:assetApi,
    release_url:expectedPage,notes:String(value.body||'这个版本没有填写更新说明。').slice(0,20000),
    published_at:value.published_at||null};
}
function networkError(error,operation){
  if(error?.name==='AbortError'||error?.name==='TimeoutError')return new Error(`${operation}已取消或连接超时，可以重新尝试。`);
  if(error?.code==='ENOSPC')return new Error('磁盘空间不足，请腾出空间后重新下载。');
  if(error?.name==='TypeError'||/net::|fetch failed|ECONN|ENOTFOUND|ETIMEDOUT/i.test(String(error?.message)))
    return new Error(`${operation}时无法连接 GitHub。请检查网络或代理后重试，也可以打开发布页面下载。`);
  return error;
}
async function limitedText(response,limit){
  if(!response.body)throw new Error('GitHub 返回了空内容，请稍后重试。');
  const reader=response.body.getReader();let size=0;const chunks=[];
  try{for(;;){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;
    if(size>limit)throw new Error('GitHub 返回的版本信息过大，请查看发布页面。');chunks.push(Buffer.from(value));}}
  finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
  return Buffer.concat(chunks).toString('utf8');
}
function createGitHubReleaseClient({request=globalThis.fetch,checkTimeoutMs=30000,idleTimeoutMs=45000}={}){
  async function check({signal}={}){
    try{
      const response=await request(releaseApi,{headers:{Accept:'application/vnd.github+json',
        'X-GitHub-Api-Version':'2022-11-28','User-Agent':'StudyForge-update-check'},credentials:'omit',cache:'no-store',
        signal:signal?AbortSignal.any([signal,AbortSignal.timeout(checkTimeoutMs)]):AbortSignal.timeout(checkTimeoutMs)});
      if(!response.ok){
        await response.body?.cancel().catch(()=>{});
        if(response.status===404)throw new Error('GitHub 还没有正式发布的安装包，请稍后再检查。');
        if(response.status===403||response.status===429){
          const reset=Number(response.headers.get('x-ratelimit-reset'))*1000;
          const wait=Number(response.headers.get('retry-after'))*1000;
          const error=new Error('GitHub 暂时限制了检查次数，请稍后重试；仍可打开发布页面。');
          error.retry_at=new Date(Math.min(Date.now()+24*3600000,Math.max(Date.now()+60000,
            Number.isFinite(reset)?reset:0,Number.isFinite(wait)?Date.now()+wait:0))).toISOString();throw error;
        }
        throw new Error(`GitHub 检查未成功（HTTP ${response.status}），可以稍后重试。`);
      }
      let value;try{value=JSON.parse(await limitedText(response,2*1024**2));}
      catch(error){if(error instanceof SyntaxError)throw new Error('GitHub 返回的不是有效版本信息，请检查网络后重试。');throw error;}
      return releaseInfo(value);
    }catch(error){throw networkError(error,'检查更新');}
  }
  async function download(info,destination,{signal,onProgress=()=>{}}={}){
    // Revalidate even persisted metadata before issuing any request.
    const tag=info.release_url?.split('/').at(-1);
    const verified=releaseInfo({tag_name:tag,html_url:info.release_url,draft:false,prerelease:false,body:info.notes,
      assets:[{id:info.asset_id,url:info.asset_api_url,name:`StudyForge-Setup-${info.version}.exe`,state:'uploaded',browser_download_url:info.url,
        size:info.size,digest:`sha256:${info.sha256}`}]});
    const partial=destination+'.part',controller=new AbortController();let watchdog,lastNotice=0;
    const abort=()=>controller.abort(signal?.reason);if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
    const touch=()=>{clearTimeout(watchdog);watchdog=setTimeout(()=>controller.abort(new Error('下载连接长时间没有响应，请重新下载。')),idleTimeoutMs);watchdog.unref?.();};
    try{
      await fsp.mkdir(path.dirname(destination),{recursive:true});await fsp.rm(partial,{force:true});touch();
      const response=await request(verified.asset_api_url||verified.url,{headers:verified.asset_api_url?{Accept:'application/octet-stream'}:{},
        credentials:'omit',cache:'no-store',signal:controller.signal});
      if(!response.ok||!response.body){await response.body?.cancel().catch(()=>{});throw new Error(`安装包下载未成功（HTTP ${response.status}），请重试或打开发布页面。`);}
      const length=response.headers.get('content-length');
      if(length!==null&&Number(length)!==verified.size){await response.body.cancel();throw new Error('下载文件大小与发布记录不符，已停止下载。');}
      let received=0;const hash=crypto.createHash('sha256'),started=Date.now();
      const meter=new Transform({transform(chunk,encoding,done){touch();received+=chunk.length;
        if(received>verified.size)return done(new Error('下载内容超过发布的大小，已停止下载。'));
        hash.update(chunk);const now=Date.now();if(now-lastNotice>=250||received===verified.size){lastNotice=now;
          onProgress({percent:received/verified.size*100,transferred:received,total:verified.size,
            bytes_per_second:received/Math.max(.001,(now-started)/1000)});}done(null,chunk);}});
      await pipeline(Readable.fromWeb(response.body),meter,fs.createWriteStream(partial,{flags:'wx',mode:0o600}),{signal:controller.signal});
      if(received!==verified.size||hash.digest('hex')!==verified.sha256)throw new Error('下载文件不完整或校验不通过，已移除未完成文件，请重新下载。');
      await fsp.rename(partial,destination);return destination;
    }catch(error){throw networkError(controller.signal.aborted&&!signal?.aborted?controller.signal.reason:error,'下载安装包');}
    finally{clearTimeout(watchdog);signal?.removeEventListener('abort',abort);await fsp.rm(partial,{force:true}).catch(()=>{});}
  }
  return {check,download};
}
module.exports={createGitHubReleaseClient,releaseInfo,releasePage,releaseApi,sourceKey,officialReleasePage};
