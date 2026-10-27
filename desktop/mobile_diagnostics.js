const https=require('node:https');
const {execFile}=require('node:child_process');
const path=require('node:path');
const {X509Certificate}=require('node:crypto');

function ipv4(value){
  if(typeof value!=='string'||!/^\d{1,3}(\.\d{1,3}){3}$/.test(value))return null;
  const parts=value.split('.').map(Number);if(parts.some(number=>number>255))return null;
  return parts.reduce((total,number)=>((total<<8)|number)>>>0,0);
}
function sameSubnet(computer,phone,mask){
  const values=[computer,phone,mask].map(ipv4);if(values.some(value=>value===null))return null;
  return ((values[0]&values[2])>>>0)===((values[1]&values[2])>>>0);
}
function probeHTTPS(address,port,ca){
  return new Promise((resolve,reject)=>{
    // The exported Android CA is DER; Node's TLS trust store accepts PEM.
    try{ca=new X509Certificate(ca).toString();}catch(error){reject(error);return;}
    let settled=false;const finish=(error,result)=>{if(settled)return;settled=true;clearTimeout(deadline);error?reject(error):resolve(result);};
    const request=https.get({hostname:address,port,path:'/',ca,rejectUnauthorized:true,agent:false},response=>{
      let body='',bytes=0;response.setEncoding('utf8');
      response.on('data',chunk=>{bytes+=Buffer.byteLength(chunk);if(bytes>128*1024){request.destroy(new Error('手机首页响应过大'));return;}body+=chunk;});
      response.on('end',()=>finish(null,{status:response.statusCode,mobilePage:body.includes('StudyForge')}));
      response.on('error',error=>finish(error));
    });
    const deadline=setTimeout(()=>request.destroy(new Error('本机 HTTPS 检测超时')),4000);
    request.on('error',error=>finish(error));
  });
}
async function windowsNetwork(){
  if(process.platform!=='win32')return null;
  const command=path.join(process.env.SystemRoot||'C:\\Windows','System32','WindowsPowerShell','v1.0','powershell.exe');
  const script="[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); [ordered]@{networks=@(Get-NetConnectionProfile | Select-Object InterfaceAlias,@{Name='category';Expression={$_.NetworkCategory.ToString()}});firewalls=@(Get-NetFirewallProfile | Select-Object Name,@{Name='enabled';Expression={$_.Enabled -eq 1}})} | ConvertTo-Json -Depth 4 -Compress";
  try{return await new Promise((resolve,reject)=>execFile(command,['-NoProfile','-NonInteractive','-EncodedCommand',Buffer.from(script,'utf16le').toString('base64')],
    {windowsHide:true,timeout:7000,maxBuffer:256*1024,encoding:'utf8'},(error,output)=>{
      if(error)return reject(error);try{resolve(JSON.parse(output.replace(/^\uFEFF/,'')));}catch(failure){reject(failure);}
    }));}catch{return {error:'无法读取 Windows 网络状态；本机 HTTPS 检测仍可使用。'};}
}
async function diagnose({status,interfaces,certificate,address,phoneIP='',network=null,probe=probeHTTPS}){
  const checks=[],tips=[],item=interfaces.find(row=>row.address===address);
  if(!item||ipv4(address)===null)throw new Error('请选择当前电脑的局域网地址');
  const port=Number(status.port);if(!Number.isInteger(port)||port<1024||port>65535)throw new Error('手机连接端口无效');
  if(phoneIP&&ipv4(phoneIP)===null)throw new Error('手机 IP 格式无效，请输入 Wi-Fi 详情里的 IPv4 地址');
  const result={url:'https://'+address+':'+port+'/',checks,tips,phone_path_verified:false};
  checks.push({level:status.running?'ok':'error',title:'电脑手机服务',detail:status.running?'正在运行 · 端口 '+port:'尚未启用，请先点击“启用手机连接”。'});
  if(!status.running)return result;
  if(!status.addresses.includes(address)){
    checks.push({level:'error',title:'网络地址已改变',detail:'当前电脑地址 '+address+' 不在这次服务启动时的地址中。请点击“重新启用”刷新网址和证书。'});
    tips.push('更换 Wi-Fi 或热点后使用新的地址，不继续打开旧二维码。');return result;
  }
  try{
    const tested=await probe(address,port,Buffer.from(certificate.data,'base64'));
    checks.push({level:tested.status===200&&tested.mobilePage?'ok':'error',title:'电脑上的加密连接与证书',
      detail:tested.status===200&&tested.mobilePage?'电脑能正常打开手机页面，连接证书也通过了检查。接下来还需用手机实际打开网址。':'服务返回 '+tested.status+'，未确认是手机学习首页。'});
  }catch(error){checks.push({level:'error',title:'电脑上的加密连接与证书',detail:error.code||error.message});}
  checks.push({level:'info',title:'手机必须使用当前网址',detail:result.url});
  const tailnet=item.kind==='tailscale';
  if(tailnet){
    checks.push({level:status.enable_tailscale&&status.tailscale?.connected?'ok':'error',title:'跨网络连接',
      detail:status.enable_tailscale&&status.tailscale?.connected?'电脑 Tailscale 已连接。手机也需打开 Tailscale 并登录同一账号；无需与电脑处于同一 Wi-Fi。':'请先连接 Tailscale，再重新启用手机连接。'});
  }else if(/virtual|vethernet|docker|vmware|vpn|wsl/i.test(item.name))tips.push('所选网卡可能是虚拟网卡或 VPN，请优先选择 Wi-Fi 或有线网卡的地址。');
  const profile=network?.networks?.find(row=>row.InterfaceAlias===item.name);
  if(profile){
    const names={Public:'Public',Private:'Private',DomainAuthenticated:'Domain'},firewall=network.firewalls?.find(row=>row.Name===names[profile.category]);
    checks.push({level:'info',title:'Windows 网络与防火墙',detail:'当前网络：'+profile.category+(firewall?'；对应 Windows 防火墙：'+(firewall.enabled?'已启用，是否放行本软件仍需核对':'未启用，不能据此判定其他网络拦截不存在'):'；未读取到对应防火墙状态')});
  }else if(network?.error)checks.push({level:'info',title:'Windows 网络状态',detail:network.error});
  if(phoneIP&&!tailnet){
    const shared=sameSubnet(address,phoneIP,item.netmask);
    checks.push({level:'info',title:'手机和电脑是否在同一网络',detail:shared===null?'无法按电脑网卡掩码判断网段。':shared?'地址看起来在同一网络，但 Wi-Fi 可能不允许设备互相访问，仍需用手机试开。':'地址不在同一网络。若没有 Tailscale 等跨网络连接，可能无法直接访问。'});
  }
  tips.push('本机自检通过只证明电脑能访问服务，尚未验证手机到电脑的路径。');
  tips.push(tailnet?'私人地址连接超时：确认两端 Tailscale 都显示已连接、属于同一账户，电脑未睡眠，账户访问规则允许此端口。':'当前地址正确却连接超时：检查手机是否连接目标 Wi-Fi、手机和电脑的 VPN/代理，以及 Wi-Fi 是否隔离设备。可用个人热点作对照，切换后重新启用并扫码新地址。');
  tips.push('若出现证书或隐私提示，才核对安卓安装的 CA 与这里导出的证书；地址变化后，同一电脑的数据目录仍使用同一个 CA。');
  return result;
}
module.exports={ipv4,sameSubnet,probeHTTPS,windowsNetwork,diagnose};
