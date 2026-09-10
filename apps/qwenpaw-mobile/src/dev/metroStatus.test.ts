import assert from "node:assert/strict";
import test from "node:test";

import { isMetroRunningStatus, metroStatusUrl } from "./metroStatus";

test("derives the Metro status URL from the loaded bundle", () => {
  assert.equal(
    metroStatusUrl(
      "http://192.168.1.18:8081/node_modules/expo-router/entry.bundle?platform=ios",
    ),
    "http://192.168.1.18:8081/status",
  );
});

test("supports IPv6 Metro hosts", () => {
  assert.equal(
    metroStatusUrl("http://[::1]:8081/index.bundle?platform=ios"),
    "http://[::1]:8081/status",
  );
});

test("falls back to Expo hostUri and ignores release file URLs", () => {
  assert.equal(
    metroStatusUrl("file:///main.jsbundle", "10.0.0.8:8081"),
    "http://10.0.0.8:8081/status",
  );
  assert.equal(metroStatusUrl("file:///main.jsbundle"), null);
});

test("accepts only the Metro running status response", () => {
  assert.equal(isMetroRunningStatus("packager-status:running\n"), true);
  assert.equal(isMetroRunningStatus("packager-status:stopped"), false);
  assert.equal(isMetroRunningStatus("<html>not metro</html>"), false);
});
