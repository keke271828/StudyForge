const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const http=require('node:http');
const {createGitHubReleaseClient,releaseInfo,releaseApi,releasePage,officialReleasePage}=require('../desktop/github_releases');

function metadata(data=Buffer.from('isolated fixture')){
  return {tag_name:'v0.0.2',draft:false,prerelease:false,
    html_url:'https://github.com/keke271828/StudyForge/releases/tag/v0.0.2',body:'# 新版本\n\n改进学习体验。',
    assets:[{name:'StudyForge-Setup-0.0.2.exe',state:'uploaded',size:data.length,
      browser_download_url:'https://github.com/keke271828/StudyForge/releases/download/v0.0.2/StudyForge-Setup-0.0.2.exe',
      digest:'sha256:'+crypto.createHash('sha256').update(data).digest('hex')}]};
}
function temporary(t){const root=fs.mkdtempSync(path.resolve(__dirname,'../build/github-release-unit-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));return path.join(root,'installer.exe');}

test('a stable official release supplies notes, exact installer and GitHub SHA256',()=>{
  const info=releaseInfo(metadata());assert.equal(info.version,'0.0.2');assert.equal(info.provider,'github');
  assert.match(info.notes,/改进学习体验/);assert.match(info.sha256,/^[a-f0-9]{64}$/);
  assert.equal(officialReleasePage(info.release_url),info.release_url);
});
for(const [name,change] of [
  ['prerelease',x=>x.prerelease=true],['draft',x=>x.draft=true],['invalid tag',x=>x.tag_name='v0.0.2-beta'],
  ['foreign repository',x=>x.html_url='https://github.com/other/StudyForge/releases/tag/v0.0.2'],
  ['foreign download',x=>x.assets[0].browser_download_url='https://other.test/install.exe'],
  ['duplicate installer',x=>x.assets.push({...x.assets[0]})],['unfinished upload',x=>x.assets[0].state='new'],
  ['missing checksum',x=>delete x.assets[0].digest],['oversized binary',x=>x.assets[0].size=5*1024**3],
  ['incomplete installer',x=>x.assets[0].size=0]])
  test('reject '+name,()=>{const value=metadata();change(value);assert.throws(()=>releaseInfo(value));});

test('external release URLs never become an open-external target',()=>{
  for(const url of ['file:///C:/Windows/','https://evil.test','https://github.com/keke271828/StudyForge/releases/tag/v0.0.2?x=y'])
    assert.equal(officialReleasePage(url),releasePage);
});

test('release checks are public and bounded; no user credential is sent',async()=>{
  let requested;const client=createGitHubReleaseClient({request:async(url,options)=>{
    requested={url,options};return new Response(JSON.stringify(metadata()));}});
  await client.check();assert.equal(requested.url,releaseApi);assert.equal(requested.options.credentials,'omit');
  assert.equal(requested.options.headers.Authorization,undefined);assert.equal(requested.options.cache,'no-store');
});

test('HTML responses, missing releases and API rate limits produce recoverable errors',async()=>{
  for(const [status,body,pattern] of [[200,'<html>network login</html>',/有效版本/],[404,'{}',/还没有正式发布/],[503,'{}',/503/]]){
    const client=createGitHubReleaseClient({request:async()=>new Response(body,{status})});await assert.rejects(client.check(),pattern);
  }
  const limited=createGitHubReleaseClient({request:async()=>new Response('{}',{status:429,headers:{'retry-after':'120'}})});
  await assert.rejects(limited.check(),error=>Boolean(error.retry_at&&new Date(error.retry_at)>Date.now()));
});

test('metadata response size is limited before JSON parsing',async()=>{
  const client=createGitHubReleaseClient({request:async()=>new Response(' '.repeat(2*1024**2+1))});
  await assert.rejects(client.check(),/过大/);
});

test('download uses a real streaming HTTP response, reports progress and verifies bytes',async t=>{
  const data=Buffer.alloc(512*1024,23),meta=metadata(data),file=temporary(t);let hits=0;
  const server=http.createServer((req,res)=>{hits++;res.writeHead(200,{'content-length':data.length});
    let offset=0;const timer=setInterval(()=>{res.write(data.subarray(offset,offset+32768));offset+=32768;
      if(offset>=data.length){clearInterval(timer);res.end();}},2);res.on('close',()=>clearInterval(timer));});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>{server.closeAllConnections();server.close();});
  const progress=[],client=createGitHubReleaseClient({request:async(url,options)=>{
    assert.equal(url,meta.assets[0].browser_download_url);return fetch(`http://127.0.0.1:${server.address().port}/installer`,options);}});
  await client.download(releaseInfo(meta),file,{onProgress:p=>progress.push(p)});
  assert.equal(hits,1);assert.ok(fs.readFileSync(file).equals(data));assert.equal(progress.at(-1).percent,100);
  assert.equal(fs.existsSync(file+'.part'),false);
});

test('bad hash, truncated data and size mismatch cannot leave a completed installer',async t=>{
  const data=Buffer.alloc(1024,7),info=releaseInfo(metadata(data));
  for(const [body,headers] of [[Buffer.alloc(1024,8),{}],[data.subarray(0,500),{}],[data,{'content-length':'123'}]]){
    const file=temporary(t),client=createGitHubReleaseClient({request:async()=>new Response(body,{headers})});
    await assert.rejects(client.download(info,file));assert.equal(fs.existsSync(file),false);assert.equal(fs.existsSync(file+'.part'),false);
  }
});

test('a cancelled stream removes its partial file and the next download can succeed',async t=>{
  const data=Buffer.alloc(256*1024,13),info=releaseInfo(metadata(data)),file=temporary(t),controller=new AbortController();
  const client=createGitHubReleaseClient({request:async()=>new Response(new ReadableStream({
    start(s){s.enqueue(data.subarray(0,32768));s.enqueue(data.subarray(32768));s.close();}}))});
  await assert.rejects(client.download(info,file,{signal:controller.signal,onProgress:()=>controller.abort()}));
  assert.equal(fs.existsSync(file),false);assert.equal(fs.existsSync(file+'.part'),false);
  await client.download(info,file);assert.ok(fs.readFileSync(file).equals(data));
});

test('persisted metadata is checked again before any download request',async t=>{
  const file=temporary(t);let calls=0;const client=createGitHubReleaseClient({request:async()=>{calls++;throw new Error('unexpected');}});
  const info={...releaseInfo(metadata()),url:'file:///C:/Windows/test.exe'};
  await assert.rejects(client.download(info,file));assert.equal(calls,0);
});

test('official asset API downloads avoid dependence on the GitHub web-page connection',async t=>{
  const data=Buffer.from('official API download fixture'),meta=metadata(data);meta.assets[0].id=1234;
  meta.assets[0].url='https://api.github.com/repos/keke271828/StudyForge/releases/assets/1234';
  const info=releaseInfo(meta),file=temporary(t);let called=false;
  const client=createGitHubReleaseClient({request:async(address,options)=>{
    called=true;assert.equal(address,meta.assets[0].url);assert.equal(options.headers.Accept,'application/octet-stream');return new Response(data);}});
  await client.download(info,file);assert.equal(called,true);assert.ok(fs.readFileSync(file).equals(data));
  await assert.rejects(client.download({...info,asset_api_url:'https://evil.test/file'},file));
});

module.exports={metadata};
