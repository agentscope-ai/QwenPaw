import assert from "node:assert/strict";
import test from "node:test";

import {
  base64Url,
  buildPlatformAuthorizeUrl,
  classifyEmbeddedOAuthNavigation,
  isPlatformOAuthAppCallback,
  isPlatformOAuthLoopbackCallback,
  parsePlatformOAuthCallback,
  resolveAndroidOAuthCallback,
  selectAndroidOAuthBrowserPackage,
  shouldUseEmbeddedAndroidOAuth,
} from "./platformOAuth";

test("Platform authorize URL uses PKCE and a loopback callback", () => {
  const value = buildPlatformAuthorizeUrl({
    codeChallenge: "challenge",
    redirectUri: "http://127.0.0.1:43210/callback/qwenpaw-mobile",
    state: "state",
  });
  const url = new URL(value);
  assert.equal(url.pathname, "/cli/login");
  assert.equal(url.searchParams.get("client_id"), "agentscope-platform-cli");
  assert.equal(url.searchParams.get("response_type"), "code");
  assert.equal(url.searchParams.get("code_challenge_method"), "S256");
  assert.equal(url.searchParams.get("scope"), "platform:control");
  assert.equal(
    url.searchParams.get("redirect_uri"),
    "http://127.0.0.1:43210/callback/qwenpaw-mobile",
  );
});

test("OAuth callback rejects state mismatch", () => {
  assert.throws(
    () =>
      parsePlatformOAuthCallback(
        "qwenpaw://platform-auth?code=code&state=other",
        "expected",
      ),
    /状态校验失败/,
  );
});

test("OAuth callback returns a verified code", () => {
  assert.equal(
    parsePlatformOAuthCallback(
      "qwenpaw://platform-auth?code=code&state=expected",
      "expected",
    ),
    "code",
  );
});

test("recognizes only the app-owned Platform callback", () => {
  assert.equal(
    isPlatformOAuthAppCallback("qwenpaw://platform-auth?code=code"),
    true,
  );
  assert.equal(
    isPlatformOAuthAppCallback("qwenpaw://platform-auth.evil?code=code"),
    false,
  );
  assert.equal(
    isPlatformOAuthAppCallback("https://platform-auth?code=code"),
    false,
  );
});

test("recognizes only the exact loopback callback allocated to the flow", () => {
  const expected = "http://127.0.0.1:43210/callback/qwenpaw-mobile";
  assert.equal(
    isPlatformOAuthLoopbackCallback(
      `${expected}?code=code&state=state`,
      expected,
    ),
    true,
  );
  assert.equal(
    isPlatformOAuthLoopbackCallback(
      "http://127.0.0.1:43211/callback/qwenpaw-mobile?code=code",
      expected,
    ),
    false,
  );
  assert.equal(
    isPlatformOAuthLoopbackCallback(
      "http://localhost:43210/callback/qwenpaw-mobile?code=code",
      expected,
    ),
    false,
  );
  assert.equal(
    isPlatformOAuthLoopbackCallback(
      "http://127.0.0.1:43210/callback/other?code=code",
      expected,
    ),
    false,
  );
});

test("base64 URL encoding removes unsafe characters", () => {
  assert.equal(base64Url("ab+c/d=="), "ab-c_d");
});

test("Android OAuth keeps a verified default Custom Tabs provider", () => {
  assert.equal(selectAndroidOAuthBrowserPackage({
    browserPackages: ["org.mozilla.firefox", "com.android.chrome"],
    defaultBrowserPackage: "org.mozilla.firefox",
    preferredBrowserPackage: "org.mozilla.firefox",
    servicePackages: ["org.mozilla.firefox", "com.android.chrome"],
  }), "org.mozilla.firefox");
});

test("Android OAuth skips a default browser without Custom Tabs service", () => {
  assert.equal(selectAndroidOAuthBrowserPackage({
    browserPackages: ["com.heytap.browser"],
    defaultBrowserPackage: "com.heytap.browser",
    preferredBrowserPackage: "com.heytap.browser",
    servicePackages: ["com.android.chrome"],
  }), "com.android.chrome");
});

test("Android OAuth trusts a vendor-visible Custom Tabs service", () => {
  assert.equal(selectAndroidOAuthBrowserPackage({
    browserPackages: [],
    servicePackages: ["com.sec.android.app.sbrowser"],
  }), "com.sec.android.app.sbrowser");
});

test("Android OAuth reports no Custom Tabs provider for embedded fallback", () => {
  assert.equal(selectAndroidOAuthBrowserPackage({
    browserPackages: ["com.heytap.browser"],
    defaultBrowserPackage: "com.heytap.browser",
    preferredBrowserPackage: "com.heytap.browser",
    servicePackages: [],
  }), null);
});

test("Android OAuth uses the embedded callback path on supported OPlus devices", () => {
  assert.equal(shouldUseEmbeddedAndroidOAuth({
    brand: "OnePlus",
    manufacturer: "OnePlus",
    sdkVersion: 36,
  }), true);
  assert.equal(shouldUseEmbeddedAndroidOAuth({
    brand: "OPPO",
    manufacturer: "OPPO",
    sdkVersion: 36,
  }), true);
  assert.equal(shouldUseEmbeddedAndroidOAuth({
    brand: "realme",
    manufacturer: "realme",
    sdkVersion: 24,
  }), true);
});

test("Android OAuth keeps system auth on unaffected devices", () => {
  assert.equal(shouldUseEmbeddedAndroidOAuth({
    brand: "OnePlus",
    manufacturer: "OnePlus",
    sdkVersion: 23,
  }), false);
  assert.equal(shouldUseEmbeddedAndroidOAuth({
    brand: "google",
    manufacturer: "Google",
    sdkVersion: 36,
  }), false);
});

test("embedded OAuth intercepts only its exact loopback callback", () => {
  const redirectUri =
    "http://127.0.0.1:43210/callback/qwenpaw-mobile";
  assert.equal(classifyEmbeddedOAuthNavigation(
    `${redirectUri}?code=ok&state=state`,
    redirectUri,
  ), "callback");
  assert.equal(classifyEmbeddedOAuthNavigation(
    "https://github.com/login",
    redirectUri,
  ), "allow");
  assert.equal(classifyEmbeddedOAuthNavigation(
    "http://example.com/unsafe",
    redirectUri,
  ), "deny");
  assert.equal(classifyEmbeddedOAuthNavigation(
    "http://127.0.0.1:43211/callback/qwenpaw-mobile?code=wrong",
    redirectUri,
  ), "deny");
});

test("Android OAuth prefers the native loopback callback", async () => {
  const callback = "http://127.0.0.1:43210/callback/qwenpaw-mobile?code=ok";
  const result = await resolveAndroidOAuthCallback(
    Promise.resolve(callback),
    Promise.resolve(null),
    10,
  );
  assert.equal(result, callback);
});

test("Android OAuth accepts an app callback returned by the browser", async () => {
  const callback = "qwenpaw://platform-auth?code=ok";
  const result = await resolveAndroidOAuthCallback(
    new Promise(() => undefined),
    Promise.resolve(callback),
    10,
  );
  assert.equal(result, callback);
});

test("Android OAuth waits briefly before treating browser close as cancel", async () => {
  const callback = "http://127.0.0.1:43210/callback/qwenpaw-mobile?code=ok";
  const nativeCallback = new Promise<string>((resolve) => {
    setTimeout(() => resolve(callback), 5);
  });
  const result = await resolveAndroidOAuthCallback(
    nativeCallback,
    Promise.resolve(null),
    30,
  );
  assert.equal(result, callback);
});

test("Android OAuth returns cancel after the callback grace period", async () => {
  const result = await resolveAndroidOAuthCallback(
    new Promise(() => undefined),
    Promise.resolve(null),
    5,
  );
  assert.equal(result, null);
});
