const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopApi", {
  getDefaultApiUrl: () => ipcRenderer.invoke("app:get-default-api-url"),
  getBootstrap: () => ipcRenderer.invoke("app:get-bootstrap"),
  saveSettings: (settings) => ipcRenderer.invoke("settings:save", settings),
  testApiEndpoint: (payload) => ipcRenderer.invoke("settings:api-test", payload),
  fetchStreams: () => ipcRenderer.invoke("backend:fetch-streams"),
});
