// Boot watchdog for the console entry. Served from public/ (not inlined)
// because the packaged Tauri app enforces a `script-src 'self'` CSP that
// blocks inline scripts. Loaded as a classic script before the module entry
// so it observes entry-chunk failures; the module entry must call
// window.__qwenpawBootWatchdog.disarm() once it has rendered.
(function () {
  "use strict";

  var BOOT_FLAG = "__qwenpawBooted";
  var HANDLE = "__qwenpawBootWatchdog";
  var RETRY_KEY = "qwenpaw:boot-retries";
  var MAX_AUTO_RELOADS = 1;
  var BOOT_TIMEOUT_MS = 15000;

  if (window[HANDLE]) {
    return;
  }

  var booted = function () {
    return window[BOOT_FLAG] === true;
  };

  var retryCount = function () {
    try {
      return parseInt(sessionStorage.getItem(RETRY_KEY) || "0", 10) || 0;
    } catch (error) {
      return 0;
    }
  };

  var storeRetries = function (count) {
    try {
      if (count > 0) {
        sessionStorage.setItem(RETRY_KEY, String(count));
      } else {
        sessionStorage.removeItem(RETRY_KEY);
      }
    } catch (error) {
      // Storage may be unavailable; the reload budget just resets per page.
    }
  };

  var content = document.querySelector(".qwenpaw-boot__content");

  var showSurface = function (reason) {
    if (document.getElementById("qwenpaw-boot-error")) {
      return;
    }
    var surface = document.createElement("div");
    surface.id = "qwenpaw-boot-error";
    surface.className = "qwenpaw-boot__error";

    var title = document.createElement("span");
    title.className = "qwenpaw-boot__error-title";
    title.textContent = "Console failed to load";

    var detail = document.createElement("span");
    detail.className = "qwenpaw-boot__error-detail";
    detail.textContent = reason;

    var reload = document.createElement("button");
    reload.type = "button";
    reload.className = "qwenpaw-boot__reload";
    reload.textContent = "Reload Console";
    reload.addEventListener("click", function () {
      window.location.reload();
    });

    surface.appendChild(title);
    surface.appendChild(detail);
    surface.appendChild(reload);
    if (content) {
      content.appendChild(surface);
    } else {
      document.body.appendChild(surface);
    }
    var label = document.querySelector(".qwenpaw-boot__label");
    if (label) {
      label.style.display = "none";
    }
  };

  // Fatal triggers share one budgeted path: auto-reload once (a reload
  // re-fetches index.html and re-resolves hashed asset names, which recovers
  // the stale-cache 404 case), then keep a manual error surface.
  var fatal = function (reason) {
    if (booted() || document.getElementById("qwenpaw-boot-error")) {
      return;
    }
    var count = retryCount();
    if (count < MAX_AUTO_RELOADS) {
      storeRetries(count + 1);
      window.location.reload();
      return;
    }
    showSurface(reason);
  };

  // Capture phase catches resource load failures (entry chunk 404s); runtime
  // errors on window arrive without a SCRIPT/LINK target.
  var onResourceError = function (event) {
    var target = event.target;
    if (target && (target.tagName === "SCRIPT" || target.tagName === "LINK")) {
      fatal("Could not load " + (target.src || target.href || "a resource"));
    }
  };

  var onError = function (event) {
    if (event.target === window) {
      fatal(event.message || "Unexpected error during startup");
    }
  };

  var onUnhandledRejection = function (event) {
    fatal("Unexpected promise rejection during startup");
  };

  var timer = setTimeout(function () {
    fatal(
      "Console did not finish loading within " + BOOT_TIMEOUT_MS / 1000 + "s",
    );
  }, BOOT_TIMEOUT_MS);

  window[HANDLE] = {
    disarm: function () {
      window[BOOT_FLAG] = true;
      clearTimeout(timer);
      window.removeEventListener("error", onResourceError, true);
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
      // Refund the budget so the next cold start still gets one auto-retry.
      storeRetries(0);
    },
  };

  window.addEventListener("error", onResourceError, true);
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onUnhandledRejection);
})();
