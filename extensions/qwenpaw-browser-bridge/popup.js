/**
 * QwenPaw Browser Bridge - Popup
 *
 * Settings UI for connection configuration and status display.
 */

const hostEl = document.getElementById("host");
const portEl = document.getElementById("port");
const workspaceEl = document.getElementById("workspace");
const dotEl = document.getElementById("dot");
const statusEl = document.getElementById("status");
const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const tabsList = document.getElementById("tabsList");

function updateUI(connected, tabs) {
  dotEl.className = connected ? "dot on" : "dot";
  statusEl.textContent = connected ? "Connected" : "Disconnected";
  connectBtn.style.display = connected ? "none" : "block";
  disconnectBtn.style.display = connected ? "block" : "none";

  if (tabs && tabs.length > 0) {
    tabsList.innerHTML = "";
    tabs.forEach((id) => {
      const item = document.createElement("div");
      item.className = "tab-item";
      item.textContent = `Tab #${id}`;
      tabsList.appendChild(item);
    });
  } else {
    tabsList.textContent = "None";
  }
}

function refreshStatus() {
  chrome.runtime.sendMessage({ type: "GET_STATUS" }, (resp) => {
    if (resp) updateUI(resp.connected, resp.managedTabs);
  });
}

async function saveSettings() {
  await chrome.storage.local.set({
    host: hostEl.value.trim() || "127.0.0.1",
    port: portEl.value.trim() || "8088",
    workspace: workspaceEl.value.trim() || "default",
  });
}

async function loadSettings() {
  const settings = await chrome.storage.local.get({
    host: "127.0.0.1",
    port: "8088",
    workspace: "default",
  });
  hostEl.value = settings.host;
  portEl.value = settings.port;
  workspaceEl.value = settings.workspace;
}

connectBtn.addEventListener("click", async () => {
  await saveSettings();
  chrome.runtime.sendMessage({ type: "CONNECT" }, () => {
    setTimeout(refreshStatus, 500);
  });
});

disconnectBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "DISCONNECT" }, () => {
    setTimeout(refreshStatus, 300);
  });
});

loadSettings();
refreshStatus();
setInterval(refreshStatus, 2000);
