import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDebugBaseUrl,
  DEFAULT_DEBUG_HOST,
  DEFAULT_DEBUG_PORT,
} from "./debug";

test("builds a debug URL from a host and port", () => {
  assert.equal(
    buildDebugBaseUrl("192.168.1.20", "9000"),
    "http://192.168.1.20:9000",
  );
});

test("falls back to the default host for invalid input", () => {
  assert.equal(
    buildDebugBaseUrl("https://paw.example.com/path", "9000"),
    `http://${DEFAULT_DEBUG_HOST}:9000`,
  );
});

test("falls back to port 8088 for invalid input", () => {
  for (const port of ["", "invalid", "0", "65536"]) {
    assert.equal(
      buildDebugBaseUrl("localhost", port),
      `http://localhost:${DEFAULT_DEBUG_PORT}`,
    );
  }
});

test("supports IPv6 debug hosts", () => {
  assert.equal(buildDebugBaseUrl("::1", "8088"), "http://[::1]:8088");
});
