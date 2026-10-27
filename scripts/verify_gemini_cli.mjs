import {readdirSync,readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const packageRoot=path.resolve('build/gemini-official-validation/node_modules/@google/gemini-cli');
const folder=path.resolve('build/gemini-official-validation/local-check');mkdirSync(folder,{recursive:true});
process.env.GEMINI_CLI_HOME=folder;
const bundle=path.join(packageRoot,'bundle');
const facade=readdirSync(bundle).find(name=>/^core-.*\.js$/.test(name));
const core=await import(pathToFileURL(path.join(bundle,facade)).href);
const config=new core.Config({sessionId:'studyforge-offline-check',targetDir:folder,cwd:folder,
  debugMode:false,model:'auto',coreTools:['__studyforge_no_native_tools__'],useRipgrep:false,
  enableAgents:false,mcpServers:{},allowedMcpServerNames:[],extensionLoader:undefined});
const registry=await config.createToolRegistry();
const names=registry.getAllToolNames();assert.deepEqual(names,[],'The real CLI must expose no native tools');
const policy=new core.PolicyEngine({rules:[{toolName:'*',decision:core.PolicyDecision.DENY,priority:999}],nonInteractive:true});
const decisions=[];
for(const name of ['read_file','write_file','run_shell_command','google_web_search','mcp_other_write']){
  const result=await policy.check({name,args:{path:'unselected-file',command:'unapproved-command'}});
  assert.equal(result.decision,core.PolicyDecision.DENY);decisions.push({name,decision:result.decision});
}
const version=JSON.parse(readFileSync(path.join(packageRoot,'package.json'),'utf8')).version;
const result={ok:true,official_version:version,registered_native_tools:names,policy_decisions:decisions,model_calls:0};
writeFileSync(path.join(folder,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
process.exit(0);
