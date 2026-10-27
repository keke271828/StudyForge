// Used only when a build is explicitly requested. It does not publish anything.
const fs=require('node:fs');
const path=require('node:path');
const {feedUrl}=require('../desktop/updates');
function releaseConfiguration(packageConfig,release){
  const url=feedUrl(release.feed_url||''),publishers=release.publishers||[];
  if(!Array.isArray(publishers)||publishers.some(x=>typeof x!=='string'||!x.trim()))throw new Error('发布者签名名称必须是非空字符串数组');
  if(url&&!publishers.length)throw new Error('正式更新源需要配置发布者签名名称及签名证书');
  const config=structuredClone(packageConfig.build);
  if(url){config.publish=[{provider:'generic',url}];config.win={...config.win,publisherName:publishers,verifyUpdateCodeSignature:true,forceCodeSigning:true};
    config.electronUpdaterCompatibility='>=2.16';}
  else delete config.publish;
  return {release:{feed_url:url,publishers},builder:config};
}
if(require.main===module){
  const root=path.resolve(__dirname,'..'),pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
  const saved=JSON.parse(fs.readFileSync(path.join(root,'desktop','release-config.json'),'utf8'));
  const result=releaseConfiguration(pkg,{feed_url:process.env.STUDYFORGE_UPDATE_URL??saved.feed_url,
    publishers:process.env.STUDYFORGE_UPDATE_PUBLISHERS?JSON.parse(process.env.STUDYFORGE_UPDATE_PUBLISHERS):saved.publishers});
  fs.mkdirSync(path.join(root,'build'),{recursive:true});
  fs.writeFileSync(path.join(root,'build','release-builder.json'),JSON.stringify(result.builder,null,2));
  fs.writeFileSync(path.join(root,'desktop','release-config.json'),JSON.stringify(result.release,null,2));
}
module.exports={releaseConfiguration};
