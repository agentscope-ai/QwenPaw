/**
 * QwenPaw Browser Bridge - Content Script
 *
 * Renders a subtle tab-level visual indicator (glowing border
 * + corner badge) and provides HITL controls via the badge.
 */

(() => {
  const HOST_ID = "__qwenpaw_indicator_host__";
  let host = null;
  let shadowRoot = null;
  let paused = false;

  function createIndicator() {
    if (document.getElementById(HOST_ID)) return;

    host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "all:initial;position:fixed;top:0;left:0;width:0;height:0;z-index:2147483647;pointer-events:none;";
    shadowRoot = host.attachShadow({ mode: "closed" });

    const style = document.createElement("style");
    style.textContent = `
      :host { all: initial; }

      /* Glowing border around the entire viewport */
      .border-overlay {
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        pointer-events: none;
        border: 2px solid rgba(99, 102, 241, 0.6);
        border-radius: 0;
        box-shadow: inset 0 0 12px rgba(99, 102, 241, 0.15);
        z-index: 2147483646;
        animation: pulse-border 3s ease-in-out infinite;
      }
      .border-overlay.paused {
        border-color: rgba(251, 191, 36, 0.6);
        box-shadow: inset 0 0 12px rgba(251, 191, 36, 0.15);
      }
      @keyframes pulse-border {
        0%, 100% { border-color: rgba(99, 102, 241, 0.6); }
        50% { border-color: rgba(99, 102, 241, 0.3); }
      }

      /* Corner badge */
      .corner-badge {
        position: fixed; top: 8px; right: 8px;
        display: flex; align-items: center; gap: 6px;
        padding: 4px 10px 4px 8px;
        background: rgba(15, 23, 42, 0.85);
        backdrop-filter: blur(8px);
        border: 1px solid rgba(99, 102, 241, 0.4);
        border-radius: 20px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 11px; color: #e2e8f0;
        pointer-events: auto;
        cursor: default;
        user-select: none;
        z-index: 2147483647;
        box-shadow: 0 2px 8px rgba(0,0,0,0.25);
        transition: opacity 0.2s;
      }
      .corner-badge:hover { opacity: 1; }
      .corner-badge .dot {
        width: 6px; height: 6px; border-radius: 50%;
        background: #4ade80;
        animation: blink 2s ease-in-out infinite;
      }
      .corner-badge .dot.paused { background: #fbbf24; animation: none; }
      @keyframes blink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
      }

      /* HITL buttons inside badge on hover */
      .hitl-buttons {
        display: none; gap: 4px; margin-left: 4px;
      }
      .corner-badge:hover .hitl-buttons { display: flex; }
      .hitl-btn {
        border: 1px solid rgba(255,255,255,0.2);
        background: rgba(255,255,255,0.08);
        color: #e2e8f0; padding: 1px 6px; border-radius: 3px;
        font-size: 10px; cursor: pointer; transition: background 0.15s;
        pointer-events: auto;
      }
      .hitl-btn:hover { background: rgba(255,255,255,0.2); }
      .hitl-btn.stop { border-color: rgba(239,68,68,0.4); }
      .hitl-btn.stop:hover { background: rgba(239,68,68,0.3); }
    `;

    const borderOverlay = document.createElement("div");
    borderOverlay.className = "border-overlay";
    borderOverlay.id = "border-overlay";

    const badge = document.createElement("div");
    badge.className = "corner-badge";

    const dot = document.createElement("span");
    dot.className = "dot";
    dot.id = "status-dot";

    const label = document.createElement("span");
    label.textContent = "QwenPaw";
    label.id = "status-label";

    const hitlBtns = document.createElement("div");
    hitlBtns.className = "hitl-buttons";

    const pauseBtn = document.createElement("button");
    pauseBtn.className = "hitl-btn";
    pauseBtn.textContent = "Pause";
    pauseBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      paused = !paused;
      pauseBtn.textContent = paused ? "Resume" : "Pause";
      dot.className = paused ? "dot paused" : "dot";
      borderOverlay.className = paused ? "border-overlay paused" : "border-overlay";
      chrome.runtime.sendMessage({ type: paused ? "HITL_PAUSE" : "HITL_RESUME" });
    });

    const stopBtn = document.createElement("button");
    stopBtn.className = "hitl-btn stop";
    stopBtn.textContent = "Stop";
    stopBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      chrome.runtime.sendMessage({ type: "HITL_STOP" });
      removeIndicator();
    });

    hitlBtns.append(pauseBtn, stopBtn);
    badge.append(dot, label, hitlBtns);
    shadowRoot.append(style, borderOverlay, badge);
    document.documentElement.appendChild(host);
  }

  function removeIndicator() {
    const el = document.getElementById(HOST_ID);
    if (el) el.remove();
    host = null;
    shadowRoot = null;
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "SHOW_BANNER") createIndicator();
    if (msg.type === "HIDE_BANNER") removeIndicator();
  });

  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "QWENPAW_SHOW_BANNER") {
      createIndicator();
    }
  });
})();
