const SOURCE = "qwenpaw-chrome-popup";

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = text;
  }
}

chrome.runtime.sendMessage(
  { source: SOURCE, method: "status.get" },
  (response) => {
    const status = response && response.connected ? "Connected" : "Not connected";
    const dot = document.getElementById("dot");
    if (dot) {
      dot.dataset.connected = response && response.connected ? "true" : "false";
    }
    setText("status", status);
    setText(
      "tabs",
      String(response && Number.isFinite(response.managedTabsCount) ? response.managedTabsCount : 0),
    );
    setText("version", response && response.version ? response.version : "-");
  },
);
