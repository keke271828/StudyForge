// Only update traffic can fall back to a separate direct session. Never changes system proxy settings.
function environmentProxy(environment=process.env){
  const value=environment.HTTPS_PROXY||environment.https_proxy||environment.ALL_PROXY||environment.all_proxy||environment.HTTP_PROXY||environment.http_proxy;
  if(!value)return '';
  try{const parsed=new URL(value);if(!['http:','https:','socks4:','socks5:'].includes(parsed.protocol)||
    parsed.username||parsed.password||parsed.search||parsed.hash||!['','/'].includes(parsed.pathname))return '';
    return `${parsed.protocol}//${parsed.host}`;
  }catch(_){return '';}
}
function createUpdateRequest({systemFetch,directFetch,configuredFetch,headerTimeoutMs=10000}){
  const routes=[configuredFetch,systemFetch,directFetch].filter(Boolean),preferred=new Map();
  return async(address,options={})=>{
    const origin=new URL(address).origin;
    const first=preferred.get(origin)??0,order=[first,...routes.map((_,i)=>i).filter(i=>i!==first)];let lastError;
    for(const index of order){
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(new Error('更新连接超时')),headerTimeoutMs);timer.unref?.();
      try{const response=await routes[index](address,{...options,signal:options.signal?
        AbortSignal.any([options.signal,controller.signal]):controller.signal});preferred.set(origin,index);return response;}
      catch(error){if(options.signal?.aborted)throw error;lastError=error;}
      finally{clearTimeout(timer);}
    }
    throw lastError;
  };
}
function createBackendUpdateRequest(base,ownerToken,request=globalThis.fetch){
  return (address,options={})=>{
    const api='https://api.github.com/repos/keke271828/StudyForge/releases/';
    let query;if(address===api+'latest')query='kind=latest';
    else if(address.startsWith(api+'assets/')&&/^\d{1,16}$/.test(address.slice((api+'assets/').length)))
      query='kind=asset&asset_id='+address.slice((api+'assets/').length);
    else throw new Error('本机更新连接仅接受 StudyForge 官方版本和附件地址');
    const headers={'X-StudyForge-Desktop-Token':ownerToken};if(options.headers?.Range)headers.Range=options.headers.Range;
    return request(base+'/api/desktop/update-transfer?'+query,{headers,signal:options.signal,cache:'no-store'}).then(async response=>{
      if(response.status===502){await response.body?.cancel().catch(()=>{});throw new TypeError('本机更新连接暂时未成功');}
      return response;
    });
  };
}
module.exports={createUpdateRequest,environmentProxy,createBackendUpdateRequest};
