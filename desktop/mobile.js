const {desktopCaller}=require('./lifecycle');
const os=require('node:os'),fs=require('node:fs');
const {diagnose,windowsNetwork}=require('./mobile_diagnostics');
function addresses(){
  return Object.entries(os.networkInterfaces()).flatMap(([name,items])=>(items||[])
    .filter(item=>item.family==='IPv4'&&!item.internal&&/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(item.address))
    .map(item=>({name,address:item.address,netmask:item.netmask})))
    .sort((a,b)=>Number(/virtual|vethernet|docker|vmware/i.test(a.name))-Number(/virtual|vethernet|docker|vmware/i.test(b.name)));
}
function connectionInterfaces(value){
  const local=addresses();
  if(value.tailscale?.connected)for(const address of value.tailscale.addresses||[]){
    if(!local.some(item=>item.address===address))local.push({name:'Tailscale · 固定私人地址',address,netmask:'255.255.255.255',kind:'tailscale'});
  }
  return local;
}
function registerMobileHandlers(ipcMain,origin,getWindow,request,dialog){
  async function call(event,path,method='GET',value){
    desktopCaller(event,origin,getWindow);
    const response=await request(path,method,value),result=await response.json();
    if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'手机连接操作失败');
    return result;
  }
  async function status(event,path='/api/mobile/status',method='GET'){
    const value=await call(event,path,method);return {...value,interfaces:connectionInterfaces(value)};
  }
  ipcMain.handle('studyforge:mobile-status',event=>status(event));
  ipcMain.handle('studyforge:mobile-network-refresh',event=>status(event,'/api/mobile/network-refresh','POST'));
  ipcMain.handle('studyforge:mobile-preferences',(event,value)=>call(event,'/api/mobile/preferences','PUT',value));
  ipcMain.handle('studyforge:mobile-tailscale-help',(event,kind)=>{
    desktopCaller(event,origin,getWindow);
    const pages={windows:'https://tailscale.com/docs/install/windows',android:'https://pkgs.tailscale.com/stable/#android',account:'https://login.tailscale.com/admin/machines'};
    if(!pages[kind])throw new Error('未知的连接设置页面');
    return require('electron').shell.openExternal(pages[kind]);
  });
  ipcMain.handle('studyforge:mobile-diagnostics',async(event,value)=>{
    const report=await status(event),interfaces=report.interfaces,address=value?.address;
    if(!interfaces.some(item=>item.address===address))throw new Error('请选择当前电脑的局域网地址');
    const [certificate,network]=await Promise.all([report.running?call(event,'/api/mobile/certificate'):Promise.resolve(null),windowsNetwork()]);
    return diagnose({status:report,interfaces,certificate,address,phoneIP:String(value?.phone_ip||'').trim(),network});
  });
  ipcMain.handle('studyforge:mobile-start',async(event,value)=>{
    const report=await status(event,'/api/mobile/network-refresh','POST'),interfaces=report.interfaces;
    if(value?.address&&!interfaces.some(item=>item.address===value.address))throw new Error('请选择本机可用的局域网地址');
    return call(event,'/api/mobile/start','POST',{addresses:interfaces.filter(item=>item.kind!=='tailscale').map(item=>item.address),
      port:value?.port||18765,auto_start:Boolean(value?.auto_start),enable_tailscale:value?.enable_tailscale===true,
      remember_days:value?.remember_days||365});
  });
  ipcMain.handle('studyforge:mobile-stop',event=>call(event,'/api/mobile/stop','POST'));
  ipcMain.handle('studyforge:mobile-pairing',event=>call(event,'/api/mobile/pairing','POST'));
  ipcMain.handle('studyforge:mobile-decide',(event,value)=>{
    if(!/^[a-f0-9]{32}$/.test(value?.id))throw new Error('设备编号无效');
    return call(event,`/api/mobile/devices/${value.id}/approve`,'POST',{approved:value.approved===true});
  });
  ipcMain.handle('studyforge:mobile-revoke',(event,id)=>{
    if(!/^[a-f0-9]{32}$/.test(id||''))throw new Error('设备编号无效');
    return call(event,`/api/mobile/devices/${id}`,'DELETE');
  });
  ipcMain.handle('studyforge:mobile-qr',(event,address)=>call(event,'/api/mobile/qr?address='+encodeURIComponent(address)));
  ipcMain.handle('studyforge:mobile-certificate',async event=>{
    const certificate=await call(event,'/api/mobile/certificate');
    const target=await dialog.showSaveDialog(getWindow(),{title:'导出手机连接证书',
      defaultPath:'StudyForge-手机连接证书.cer',filters:[{name:'CA 证书',extensions:['cer']}]});
    if(target.canceled)return {saved:false};
    fs.writeFileSync(target.filePath,Buffer.from(certificate.data,'base64'));
    return {saved:true,path:target.filePath,fingerprint:certificate.fingerprint};
  });
}
module.exports={registerMobileHandlers,addresses};
