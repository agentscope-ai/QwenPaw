import assert from "node:assert/strict";
import test from "node:test";

import {
  inferPlatformAccessPath,
  isPlatformGatewayAuthResponse,
  platformAccessPath,
  platformConsoleBaseUrl,
} from "./platformGatewayModel";

test("distinguishes Platform HTML auth errors from QwenPaw JSON errors", () => {
  assert.equal(isPlatformGatewayAuthResponse(401, "text/html"), true);
  assert.equal(isPlatformGatewayAuthResponse(
    403,
    "text/html; charset=utf-8",
  ), true);
  assert.equal(isPlatformGatewayAuthResponse(401, "application/json"), false);
  assert.equal(isPlatformGatewayAuthResponse(404, "text/html"), false);
});

test("extracts the official Platform QwenPaw access API path", () => {
  assert.equal(platformAccessPath(
    "https://platform.agentscope.io/api/v1/app/access?appId=paw-1",
  ), "/api/v1/app/access?appId=paw-1");
  assert.equal(
    platformAccessPath("/api/v1/app/access?appId=paw-1"),
    "/api/v1/app/access?appId=paw-1",
  );
  assert.equal(platformAccessPath("https://paw.example.com"), null);
});

test("reads the QwenPaw console origin from Platform access responses", () => {
  assert.equal(platformConsoleBaseUrl({
    data: {
      console_base_url: "https://paw.example.com/entry?ticket=temporary",
    },
  }), "https://paw.example.com");
  assert.equal(platformConsoleBaseUrl({ data: {} }), null);
});

test("migrates saved Platform connections to their access API path", () => {
  assert.equal(inferPlatformAccessPath(
    "https://01a038e7-d1e4-78b5-80c5-ccce8a74830e.qwenpaw.platform.agentscope.io",
  ), "/api/v1/qwenpaw/01a038e7-d1e4-78b5-80c5-ccce8a74830e");
  assert.equal(inferPlatformAccessPath("https://paw.example.com"), null);
});
