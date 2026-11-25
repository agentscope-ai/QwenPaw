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
  async function replayRequestInit(input, init) {
    var options = {};
    for (var key of [
      "method", "headers", "mode", "credentials", "cache", "redirect",
      "referrer", "referrerPolicy", "integrity", "keepalive", "duplex", "signal",
    ]) {
      var option = init == null ? undefined : init[key];
      options[key] = option === undefined ? input[key] : option;
    }
    options.body = init == null ? undefined : init.body;
    if (options.body == null && input.body !== null) {
      if (input.bodyUsed) throw new TypeError("Request body is already used");
      // Keep a fixed-length body instead of turning a regular POST into a streaming upload.
      var relay = new TransformStream();
      var signal = options.signal ?? undefined;
      try {
        var result = await Promise.all([
          input.body.pipeTo(relay.writable, { signal: signal }),
          new Response(relay.readable).arrayBuffer(),
        ]);
        options.body = result[1];
      } catch (error) {
        if (signal?.aborted) throw signal.reason;
        throw error;
      }
    }
    return options;
  }

  var originalFetch = window.fetch;
  if (typeof originalFetch === "function") {
    window.fetch = async function (input, init) {
      var isRequest = input instanceof Request;
      var target = hostRequestUrl(isRequest ? input.url : String(input));
      if (!target) return originalFetch.call(this, input, init);

      var options = isRequest ? await replayRequestInit(input, init) : {};
      var headers = new Headers(isRequest ? options.headers : init?.headers);
      var token = hostToken();
      if (token && !headers.has("Authorization")) {
        headers.set("Authorization", "Bearer " + token);
      }
      if (!headers.has("X-Agent-Id")) headers.set("X-Agent-Id", workspaceId());
      options.headers = headers;
      return originalFetch.call(this, target, Object.setPrototypeOf(options, init ?? null));
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
