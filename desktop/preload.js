const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('studyforgeDesktop', {
  mobileStatus: () => ipcRenderer.invoke('studyforge:mobile-status'),
  mobileNetworkRefresh: () => ipcRenderer.invoke('studyforge:mobile-network-refresh'),
  mobilePreferences: value => ipcRenderer.invoke('studyforge:mobile-preferences',value),
  mobileTailscaleHelp: kind => ipcRenderer.invoke('studyforge:mobile-tailscale-help',kind),
  mobileDiagnostics: value => ipcRenderer.invoke('studyforge:mobile-diagnostics',value),
  mobileStart: value => ipcRenderer.invoke('studyforge:mobile-start',value),
  mobileStop: () => ipcRenderer.invoke('studyforge:mobile-stop'),
  mobilePairing: () => ipcRenderer.invoke('studyforge:mobile-pairing'),
  mobileDecide: value => ipcRenderer.invoke('studyforge:mobile-decide',value),
  mobileRevoke: id => ipcRenderer.invoke('studyforge:mobile-revoke',id),
  mobileQR: address => ipcRenderer.invoke('studyforge:mobile-qr',address),
  mobileCertificate: () => ipcRenderer.invoke('studyforge:mobile-certificate'),
  copyText: text => ipcRenderer.invoke('studyforge:copy-text', text),
  chooseDirectory: () => ipcRenderer.invoke('studyforge:choose-directory'),
  importBrowserPage: url => ipcRenderer.invoke('studyforge:import-browser-page', url),
  desktopStatus: () => ipcRenderer.invoke('studyforge:desktop-status'),
  startupStatus: () => ipcRenderer.invoke('studyforge:startup-status'),
  saveStartupSettings: value => ipcRenderer.invoke('studyforge:startup-save',value),
  notificationStatus: () => ipcRenderer.invoke('studyforge:notification-status'),
  testNotification: () => ipcRenderer.invoke('studyforge:notification-test'),
  openNotification: id => ipcRenderer.invoke('studyforge:notification-open',id),
  onNotificationChanged: callback => {
    const changed=(_event,value)=>callback(value);ipcRenderer.on('studyforge:notification-changed',changed);
    return ()=>ipcRenderer.removeListener('studyforge:notification-changed',changed);
  },
  windowState: () => ipcRenderer.invoke('studyforge:window-state'),
  setFullscreen: value => ipcRenderer.invoke('studyforge:window-fullscreen',value),
  onWindowChanged: callback => {
    const changed=(_event,value)=>callback(value);ipcRenderer.on('studyforge:window-changed',changed);
    return ()=>ipcRenderer.removeListener('studyforge:window-changed',changed);
  },
  hideToTray: () => ipcRenderer.invoke('studyforge:hide-to-tray'),
  quit: () => ipcRenderer.invoke('studyforge:quit'),
  updateStatus: () => ipcRenderer.invoke('studyforge:update-status'),
  saveUpdateSettings: value => ipcRenderer.invoke('studyforge:update-save',value),
  checkUpdates: () => ipcRenderer.invoke('studyforge:update-check'),
  downloadUpdate: () => ipcRenderer.invoke('studyforge:update-download'),
  installUpdate: () => ipcRenderer.invoke('studyforge:update-install'),
  rollbackUpdate: () => ipcRenderer.invoke('studyforge:update-rollback'),
  openUpdateRecovery: () => ipcRenderer.invoke('studyforge:update-recovery'),
  onUpdateChanged: callback => {
    const changed=(_event,value)=>callback(value);ipcRenderer.on('studyforge:update-changed',changed);
    return ()=>ipcRenderer.removeListener('studyforge:update-changed',changed);
  },
  onDesktopEvent: callback => {
    const hidden=()=>callback('hidden');
    const quitting=()=>callback('quitting');
    const visible=()=>callback('visible');
    const navigate=(_event,view)=>callback('navigate',view);
    ipcRenderer.on('studyforge:desktop-hidden',hidden);
    ipcRenderer.on('studyforge:desktop-quitting',quitting);
    ipcRenderer.on('studyforge:desktop-visible',visible);
    ipcRenderer.on('studyforge:desktop-navigate',navigate);
    return ()=>{
      ipcRenderer.removeListener('studyforge:desktop-hidden',hidden);
      ipcRenderer.removeListener('studyforge:desktop-quitting',quitting);
      ipcRenderer.removeListener('studyforge:desktop-visible',visible);
      ipcRenderer.removeListener('studyforge:desktop-navigate',navigate);
    };
  }
});
