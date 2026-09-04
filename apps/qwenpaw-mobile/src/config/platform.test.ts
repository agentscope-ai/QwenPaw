import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_PLATFORM_BASE_URL, resolvePlatformBaseUrl } from "./platform";

test("uses production Platform by default", () => {
  assert.equal(resolvePlatformBaseUrl(), DEFAULT_PLATFORM_BASE_URL);
});

test("accepts an HTTPS Platform environment override", () => {
  assert.equal(
    resolvePlatformBaseUrl("https://platform-pre.agentscope.io/"),
    "https://platform-pre.agentscope.io",
  );
});

test("accepts an HTTP loopback override for local development", () => {
  assert.equal(
    resolvePlatformBaseUrl("http://127.0.0.1:19090"),
    "http://127.0.0.1:19090",
  );
});

test("rejects unsafe or malformed Platform overrides", () => {
  assert.equal(
    resolvePlatformBaseUrl("http://platform-pre.agentscope.io"),
    DEFAULT_PLATFORM_BASE_URL,
  );
  assert.equal(
    resolvePlatformBaseUrl("https://platform-pre.agentscope.io/path"),
    DEFAULT_PLATFORM_BASE_URL,
  );
});
