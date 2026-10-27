const path=require('node:path');
const {execFileSync}=require('node:child_process');

// Parse the Windows argv quoting rules, including escaped backslashes/quotes.
// Only our own Run value is inspected; the command is never evaluated here.
function windowsArgv(command){
  const values=[];let i=0;
  while(i<command.length){
    while(/\s/.test(command[i]||'')&&i<command.length)i++;
    if(i===command.length)break;
    let value='',quoted=false;
    while(i<command.length&&(quoted||!/[\t ]/.test(command[i]))){
      let slashes=0;while(command[i]==='\\'){slashes++;i++;}
      if(command[i]==='"'){
        value+='\\'.repeat(Math.floor(slashes/2));
        if(slashes%2)value+='"';else quoted=!quoted;
        i++;
      }else{value+='\\'.repeat(slashes);if(i<command.length&&(quoted||!/[\t ]/.test(command[i])))value+=command[i++];}
    }
    if(quoted)throw new Error('Windows 启动命令引号不完整');
    values.push(value);
  }
  return values;
}

function readWindowsEntry(name){
  if(!/^[A-Za-z0-9._-]{1,160}$/.test(name))throw new Error('启动项名称无效');
  // reg.exe emits the current OEM code page when stdout is redirected. Using
  // UTF-8 on that stream silently corrupts Chinese user names and install paths.
  // Read only these two values through .NET's Unicode API in one process.
  const executable=path.join(process.env.SystemRoot||'C:\\Windows','System32','WindowsPowerShell','v1.0','powershell.exe');
  const script=`$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$run=$null;$approval=$null
try {
  $run=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\\Microsoft\\Windows\\CurrentVersion\\Run',$false)
  $approval=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run',$false)
  $command=$null;$state=$null
  if($run){$command=$run.GetValue('${name}',$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)}
  if($approval){$bytes=$approval.GetValue('${name}');if($bytes -is [byte[]] -and $bytes.Length -gt 0){$state=[int]$bytes[0]}}
  @{command=$command;state=$state}|ConvertTo-Json -Compress
} finally {
  if($run){$run.Dispose()};if($approval){$approval.Dispose()}
}`;
  let value;
  try{value=JSON.parse(execFileSync(executable,['-NoProfile','-NonInteractive','-NoLogo','-EncodedCommand',Buffer.from(script,'utf16le').toString('base64')],{encoding:'utf8',windowsHide:true,timeout:5000,stdio:['ignore','pipe','pipe']}));}
  catch(error){throw new Error('无法核对 Windows 启动项：'+(error.code||error.message));}
  if(typeof value.command!=='string'||!value.command.trim())return null;
  const command=value.command.trim(),argv=windowsArgv(command);
  if(!argv.length)return null;
  const state=value.state;
  return {name,path:argv[0],args:argv.slice(1),scope:'user',enabled:state===null||state===2||state===6,command};
}
module.exports={windowsArgv,readWindowsEntry};
