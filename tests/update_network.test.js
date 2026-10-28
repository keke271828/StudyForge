const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createUpdateRequest,environmentProxy,createBackendUpdateRequest}=require('../desktop/update_network');

test('a transport failure falls back only for update requests and remembers the working route',async()=>{
  let system=0,direct=0;const request=createUpdateRequest({systemFetch:async()=>{system++;throw new TypeError('fetch failed');},
    directFetch:async(url,options)=>{direct++;assert.equal(options.credentials,'omit');return new Response('ok');}});
  for(let i=0;i<2;i++)assert.equal(await (await request('https://api.github.com/',{credentials:'omit'})).text(),'ok');
  assert.equal(system,1);assert.equal(direct,2);
});

test('a configured environment proxy takes precedence without modifying process settings',async()=>{
  const original={HTTPS_PROXY:'http://127.0.0.1:7899'},before=JSON.stringify(original);
  assert.equal(environmentProxy(original),'http://127.0.0.1:7899');assert.equal(JSON.stringify(original),before);
  for(const value of ['file:///tmp/test','http://user:password@example.test:80','https://example.test/?token=x'])
    assert.equal(environmentProxy({HTTPS_PROXY:value}),'');
  let system=0,direct=0;const request=createUpdateRequest({configuredFetch:async()=>new Response('configured'),
    systemFetch:async()=>system++,directFetch:async()=>direct++});
  assert.equal(await (await request('https://api.github.com/')).text(),'configured');assert.equal(system+direct,0);
});

test('HTTP failures including rate limits do not switch route or multiply requests',async()=>{
  let direct=0;const request=createUpdateRequest({systemFetch:async()=>new Response('{}',{status:429}),directFetch:async()=>direct++});
  assert.equal((await request('https://api.github.com/')).status,429);assert.equal(direct,0);
});

test('local transport accepts only official API paths and keeps its owner token local',async()=>{
  const calls=[],request=createBackendUpdateRequest('http://127.0.0.1:1234','owner',async(address,options)=>{
    calls.push({address,options});return new Response('{}');});
  await request('https://api.github.com/repos/keke271828/StudyForge/releases/latest');
  assert.equal(calls[0].address,'http://127.0.0.1:1234/api/desktop/update-transfer?kind=latest');
  assert.equal(calls[0].options.headers['X-StudyForge-Desktop-Token'],'owner');
  assert.throws(()=>request('https://evil.test/'));assert.throws(()=>request('https://api.github.com/repos/other/repo'));
});

test('API fallback does not force installer downloads to use the same route',async()=>{
  const routes=[];const request=createUpdateRequest({systemFetch:async url=>{
    routes.push('system:'+new URL(url).host);if(url.includes('api.github.com'))throw new Error('API proxy failed');return new Response('binary');},
    directFetch:async url=>{routes.push('direct:'+new URL(url).host);return new Response('metadata');}});
  await request('https://api.github.com/repos/test');await request('https://github.com/test.exe');
  assert.deepEqual(routes,['system:api.github.com','direct:api.github.com','system:github.com']);
});

test('user cancellation does not start another request',async()=>{
  const controller=new AbortController();controller.abort();let direct=0;
  const request=createUpdateRequest({systemFetch:async(url,{signal})=>{signal.throwIfAborted();},directFetch:async()=>direct++});
  await assert.rejects(request('https://api.github.com/',{signal:controller.signal}));assert.equal(direct,0);
});

test('the header timeout does not interrupt a successfully connected download body',async()=>{
  let requestSignal;const request=createUpdateRequest({headerTimeoutMs:10,systemFetch:async(url,{signal})=>{
    requestSignal=signal;return new Response('body');},directFetch:async()=>{throw new Error('unexpected fallback');}});
  const response=await request('https://github.com/');await new Promise(r=>setTimeout(r,25));
  assert.equal(requestSignal.aborted,false);assert.equal(await response.text(),'body');
});

test('unresponsive system connections have a bounded fallback',async()=>{
  const keepAlive=setTimeout(()=>{},1000);try{
    const request=createUpdateRequest({headerTimeoutMs:10,systemFetch:async(url,{signal})=>new Promise((resolve,reject)=>{
      signal.addEventListener('abort',()=>reject(signal.reason),{once:true});}),directFetch:async()=>new Response('direct')});
    assert.equal(await (await request('https://github.com/')).text(),'direct');
  }finally{clearTimeout(keepAlive);}
});
