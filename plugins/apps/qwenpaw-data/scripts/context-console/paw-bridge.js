/**
 * paw-bridge.js — injected ahead of the embedded Context console bundle.
 *
 * The console build is served same-origin from the QwenPaw host
 * (/api/frontend_plugin/qwenpaw-data/files/...), so it can read the host auth
 * token from localStorage. QwenPaw authenticates /api/* requests with a
 * Bearer header, while the Context console issues plain axios/fetch calls,
 * so this shim resolves backend URLs through the host and attaches the host
 * token to every same-origin qwenpaw-data PawApp request.
 *
 * This file is copied verbatim by scripts/sync-context-ui.sh; it must stay
 * dependency-free, classic-script (non-module) JavaScript.
 */
(function () {
  "use strict";

  var API_PREFIX = "/api/qwenpaw-data/";
  var TOKEN_KEY = "qwenpaw_auth_token";

  // Route the console's auth-status probe through the context gateway.
  if (!window.__VITE_AUTH_API_URL__) {
    window.__VITE_AUTH_API_URL__ = "/api/qwenpaw-data/context";
  }

  function hostToken() {
    try {
      return window.localStorage.getItem(TOKEN_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function hostRequestUrl(url) {
    try {
      var resolved = new URL(url, window.location.href);
      if (resolved.origin !== window.location.origin || !resolved.pathname.startsWith(API_PREFIX)) return null;
      var host = window.parent.QwenPaw && window.parent.QwenPaw.host;
      var mounted;
      if (host && host.getApiUrl) {
        mounted = new URL(host.getApiUrl(resolved.pathname.slice(4)), window.location.origin);
      } else {
        var marker = "/api/frontend_plugin/";
        var markerIndex = window.location.pathname.lastIndexOf(marker);
        var basePath = markerIndex < 0 ? "" : window.location.pathname.slice(0, markerIndex);
        mounted = new URL(basePath + resolved.pathname, window.location.origin);
      }
      if (mounted.origin !== resolved.origin) return null;
      mounted.search = resolved.search;
      return mounted.href;
    } catch (error) {
      return false;
    }
  }

  // --- fetch ---------------------------------------------------------------
  var originalFetch = window.fetch;
  if (typeof originalFetch === "function") {
    window.fetch = async function (input, init) {
      var url = input instanceof Request ? input.url : String(input);
      var target = hostRequestUrl(url);
      if (target) {
        if (input instanceof Request) {
          var replayInit = Object.assign({}, init);
          for (var key of [
            "method", "headers", "mode", "credentials", "cache", "redirect",
            "referrer", "referrerPolicy", "integrity", "keepalive", "duplex",
            "signal",
          ]) {
            var option = Object.prototype.hasOwnProperty.call(replayInit, key)
              ? replayInit[key]
              : (init == null ? undefined : init[key]);
            replayInit[key] = option === undefined ? input[key] : option;
          }
          var body = init == null ? undefined : init.body;
          if (body !== undefined) {
            replayInit.body = body;
          } else if (input.bodyUsed) {
            throw new TypeError("Request body is already used");
          } else if (input.body !== null) {
            replayInit.body = await input.arrayBuffer();
          }
          input = target;
          init = replayInit;
        } else {
          input = target;
        }
        var token = hostToken();
        var headers = new Headers(
          (init && init.headers) ||
            (input && typeof input.url === "string" ? input.headers : undefined),
        );
        if (token && !headers.has("Authorization")) {
          headers.set("Authorization", "Bearer " + token);
        }
        init = Object.assign({}, init, { headers: headers });
      }
      return originalFetch.call(this, input, init);
    };
  }

  // --- XMLHttpRequest (axios) ----------------------------------------------
  var xhrProto = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
  if (xhrProto) {
    var originalOpen = xhrProto.open;
    var originalSend = xhrProto.send;
    var originalSetHeader = xhrProto.setRequestHeader;

    xhrProto.open = function (method, url) {
      var target = hostRequestUrl(url);
      this.__pawNeedsHostAuth = Boolean(target);
      if (target) arguments[1] = target;
      this.__pawHasAuthHeader = false;
      return originalOpen.apply(this, arguments);
    };

    xhrProto.setRequestHeader = function (name, value) {
      if (String(name).toLowerCase() === "authorization") {
        this.__pawHasAuthHeader = true;
      }
      return originalSetHeader.call(this, name, value);
    };

    xhrProto.send = function () {
      var token = hostToken();
      if (token && this.__pawNeedsHostAuth && !this.__pawHasAuthHeader) {
        originalSetHeader.call(this, "Authorization", "Bearer " + token);
      }
      return originalSend.apply(this, arguments);
    };
  }

  // --- Model Configuration: explain the first-run default -------------------
  // The app owns its LLM configuration (same as standalone qwenpaw-data-cli);
  // the QwenPaw host model only seeds it on first run. Surface that in the
  // LLM card using the console's own Alert styling: clone the embedding
  // card's info alert so the note matches it pixel for pixel, and render a
  // single language following the console's language setting.
  var NOTE_ATTR = "data-paw-llm-tie-note";
  var NOTE_TEXT = {
    en:
      "Defaults to the QwenPaw host model on first run. " +
      "Afterwards this setting is owned by the app.",
    zh:
      "\u9996\u6b21\u8fd0\u884c\u65f6\u9ed8\u8ba4\u7ee7\u627f QwenPaw " +
      "\u5bbf\u4e3b\u6a21\u578b\uff1b\u6b64\u540e\u8be5\u914d\u7f6e\u5f52 " +
      "app \u81ea\u6709\u3002",
  };

  function consoleLanguage() {
    try {
      var stored = window.localStorage.getItem("language");
      if (stored === "zh" || stored === "en") return stored;
    } catch (error) {
      /* storage unavailable */
    }
    var nav = (navigator.language || "en").toLowerCase();
    return nav.indexOf("zh") === 0 ? "zh" : "en";
  }

  function findLlmCardBody() {
    var heads = document.querySelectorAll(".ant-card-head");
    for (var i = 0; i < heads.length; i += 1) {
      if ((heads[i].textContent || "").indexOf("LLM") === -1) continue;
      var card = heads[i].parentElement;
      return card ? card.querySelector(".ant-card-body") : null;
    }
    return null;
  }

  function annotateLlmCard() {
    if (window.location.hash.indexOf("/model-config") === -1) return;
    if (document.querySelector("[" + NOTE_ATTR + "]")) return;
    var body = findLlmCardBody();
    if (!body) return;
    var text = NOTE_TEXT[consoleLanguage()];
    var template = document.querySelector(".ant-card-body .ant-alert-info");
    var note;
    if (template) {
      note = template.cloneNode(true);
      note.classList.remove("ant-alert-with-description");
      var message = note.querySelector(".ant-alert-message") || note;
      message.textContent = text;
      var description = note.querySelector(".ant-alert-description");
      if (description) description.remove();
    } else {
      note = document.createElement("div");
      note.style.cssText =
        "display:flex;align-items:flex-start;gap:8px;padding:9px 12px;" +
        "border-radius:8px;background:#e6f4ff;color:rgba(0,0,0,0.88);" +
        "font-size:14px;line-height:1.57;";
      note.textContent = text;
    }
    note.setAttribute(NOTE_ATTR, "true");
    note.style.marginBottom = "16px";
    body.insertBefore(note, body.firstChild);
  }

  var observer = new MutationObserver(function () {
    annotateLlmCard();
  });
  if (document.documentElement) {
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
  }
  window.addEventListener("hashchange", annotateLlmCard);
})();
