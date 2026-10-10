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

  function hostToken() {
    try {
      return window.localStorage.getItem(TOKEN_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function needsHostAuth(url) {
    try {
      var resolved = new URL(url, window.location.href);
      return (
        resolved.origin === window.location.origin &&
        resolved.pathname.indexOf(API_PREFIX) === 0
      );
    } catch (error) {
      return false;
    }
  }

  // --- fetch ---------------------------------------------------------------
  var originalFetch = window.fetch;
  if (typeof originalFetch === "function") {
    window.fetch = function (input, init) {
      var url =
        typeof input === "string"
          ? input
          : input && typeof input.url === "string"
            ? input.url
            : "";
      var token = hostToken();
      if (token && needsHostAuth(url)) {
        var headers = new Headers(
          (init && init.headers) ||
            (input && typeof input.url === "string" ? input.headers : undefined),
        );
        if (!headers.has("Authorization")) {
          headers.set("Authorization", "Bearer " + token);
        }
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
      this.__pawNeedsHostAuth = needsHostAuth(url);
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
})();
