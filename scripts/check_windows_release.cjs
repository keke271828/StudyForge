// Check the actual local release after electron-builder has completed.
// Writes only this release's manifest and checksum; never installs or publishes.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const asar=require('@electron/asar');
const root=path.resolve(__dirname,'..'),pkg=require('../package.json');
async function fingerprint(file){
  const hash=crypto.createHash('sha256');
  for await(const chunk of fs.createReadStream(file))hash.update(chunk);
  return {path:file,bytes:fs.statSync(file).size,sha256:hash.digest('hex').toUpperCase()};
}
function files(folder){return fs.readdirSync(folder,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?files(path.join(folder,entry.name)):[path.join(folder,entry.name)]);}
async function main(){
  const version=pkg.version;assert(/^\d+\.\d+\.\d+$/.test(version));
  const unpacked=path.join(root,'dist','win-unpacked'),archive=path.join(unpacked,'resources','app.asar');
  const bundled=JSON.parse(asar.extractFile(archive,'package.json').toString('utf8'));
  assert.equal(bundled.version,version,'Bundled version is stale');
  assert.equal(bundled.license,'AGPL-3.0-only','Bundled license is stale');
  const ffmpegLicense='third_party/ffmpeg/COPYING.GPLv3';
  assert(asar.extractFile(archive,ffmpegLicense).equals(fs.readFileSync(path.join(root,ffmpegLicense))),'Missing FFmpeg GPL license in app archive');
  assert(fs.readFileSync(path.join(unpacked,'licenses',ffmpegLicense)).equals(fs.readFileSync(path.join(root,ffmpegLicense))),'Missing installed FFmpeg GPL license');
  for(const name of ['LICENSE','THIRD_PARTY_NOTICES.md']){
    const source=fs.readFileSync(path.join(root,name));
    assert(asar.extractFile(archive,name).equals(source),'Missing license in app archive: '+name);
    assert(fs.readFileSync(path.join(unpacked,'licenses',name)).equals(source),'Missing installed license: '+name);
    assert(fs.readFileSync(path.join(unpacked,'resources','backend','_internal','licenses',name)).equals(source),'Missing backend license: '+name);
  }
  const desktop={};
  for(const source of files(path.join(root,'desktop'))){
    const native=path.relative(root,source),relative=native.split(path.sep).join('/'),shipped=asar.extractFile(archive,native);
    assert(shipped.equals(fs.readFileSync(source)),'Stale desktop source: '+relative);
    desktop[relative]=crypto.createHash('sha256').update(shipped).digest('hex');
  }
  const records={};
  for(const [name,file] of Object.entries({installer:path.join(root,'dist',`StudyForge-Setup-${version}.exe`),
      application:path.join(unpacked,'StudyForge.exe'),backend:path.join(unpacked,'resources','backend','StudyForgeBackend.exe')})){
    assert(fs.statSync(file).size>1024*1024,'Empty release binary: '+file);records[name]=await fingerprint(file);
  }
  const dedup=JSON.parse(fs.readFileSync(path.join(root,'build','cuda-duplicate-report.json'),'utf8'));
  const internal=path.join(unpacked,'resources','backend','_internal');
  for(const row of dedup.removed_files){
    assert(!fs.existsSync(path.join(internal,row.removed)),'Duplicate CUDA file returned');
    const kept=await fingerprint(path.join(internal,row.retained));
    assert.equal(kept.bytes,row.bytes);assert.equal(kept.sha256.toLowerCase(),row.sha256);
  }
  const licenses=[];
  const cudaDirectory=path.join(root,'resources','asr-cuda');
  for(const source of (fs.existsSync(cudaDirectory)?files(cudaDirectory):[]).filter(p=>/licen[sc]e|notice/i.test(path.basename(p)))){
    const relative=path.relative(path.join(root,'resources','asr-cuda'),source);
    assert(fs.readFileSync(path.join(internal,'resources','asr-cuda',relative)).equals(fs.readFileSync(source)),'CUDA license missing: '+relative);
    licenses.push(relative);
  }
  const result={ok:true,version,created_at_utc:new Date().toISOString(),desktop_sources_match:true,
    desktop_source_sha256:desktop,...records,cuda_deduplication:{...dedup,retained_hashes_verified:true,licenses},installed:false,published:false};
  fs.writeFileSync(records.installer.path+'.sha256.txt',records.installer.sha256+'  '+path.basename(records.installer.path)+'\r\n','ascii');
  fs.writeFileSync(path.join(root,'build',`release-${version}-artifacts.json`),JSON.stringify(result,null,2),'utf8');
  console.log(JSON.stringify({ok:true,version,desktop_files_checked:Object.keys(desktop).length,...records}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
