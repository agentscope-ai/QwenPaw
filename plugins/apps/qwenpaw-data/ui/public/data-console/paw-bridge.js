/**
 * paw-bridge.js — injected ahead of the embedded engine console bundle.
 *
 * The console build is served same-origin from the QwenPaw host
 * (/api/frontend_plugin/qwenpaw-data/files/...), so it can read the host
 * auth token from localStorage. QwenPaw authenticates /api/* requests with
 * a Bearer header, while the console issues plain fetch calls, so this
 * shim attaches the host token to every same-origin request that targets
 * the qwenpaw-data PawApp backend (/api/qwenpaw-data/...).
 *
 * This file is copied verbatim by scripts/update-data-console.sh; it must stay
 * dependency-free, classic-script (non-module) JavaScript.
 */
(function () {
  "use strict";

  var API_PREFIX = "/api/qwenpaw-data/";
  var TOKEN_KEY = "qwenpaw_auth_token";

  function workspaceId() {
    try {
      return window.parent.QwenPaw.host.getSelectedAgentId() || "default";
    } catch (error) {
      return "default";
    }
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
      if (!host || !host.getApiUrl) return resolved.href;
      var mounted = new URL(host.getApiUrl(resolved.pathname.slice(4)), window.location.origin);
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
    window.fetch = function (input, init) {
      var url = input instanceof Request ? input.url : String(input);
      var target = hostRequestUrl(url);
      if (target) {
        input = input instanceof Request ? new Request(target, input) : target;
        var token = hostToken();
        var headers = new Headers(
          (init && init.headers) ||
            (input && typeof input.url === "string" ? input.headers : undefined),
        );
        if (token && !headers.has("Authorization")) {
          headers.set("Authorization", "Bearer " + token);
        }
        if (!headers.has("X-Agent-Id")) headers.set("X-Agent-Id", workspaceId());
        init = Object.assign({}, init, { headers: headers });
      }
      return originalFetch.call(this, input, init);
    };
  }

  // --- XMLHttpRequest ------------------------------------------------------
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
      this.__pawHasAgentHeader = false;
      return originalOpen.apply(this, arguments);
    };

    xhrProto.setRequestHeader = function (name, value) {
      if (String(name).toLowerCase() === "authorization") {
        this.__pawHasAuthHeader = true;
      }
      if (String(name).toLowerCase() === "x-agent-id") {
        this.__pawHasAgentHeader = true;
      }
      return originalSetHeader.call(this, name, value);
    };

    xhrProto.send = function () {
      var token = hostToken();
      if (this.__pawNeedsHostAuth && !this.__pawHasAgentHeader) {
        originalSetHeader.call(this, "X-Agent-Id", workspaceId());
      }
      if (token && this.__pawNeedsHostAuth && !this.__pawHasAuthHeader) {
        originalSetHeader.call(this, "Authorization", "Bearer " + token);
      }
      return originalSend.apply(this, arguments);
    };
  }
})();
