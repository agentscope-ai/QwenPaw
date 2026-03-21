const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // App info
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  getAppPath: (name) => ipcRenderer.invoke('get-app-path', name),

  // App control
  restartApp: () => ipcRenderer.invoke('restart-app'),

  // Platform info
  platform: process.platform,
  isPackaged: process.defaultApp !== undefined,

  // Logging
  log: (...args) => console.log('[Renderer]', ...args),
  error: (...args) => console.error('[Renderer]', ...args)
});

// Catch errors and report to main process
window.addEventListener('error', (event) => {
  console.error('[Renderer Error]', event.error);
});

window.addEventListener('unhandledrejection', (event) => {
  console.error('[Renderer Unhandled Rejection]', event.reason);
});
