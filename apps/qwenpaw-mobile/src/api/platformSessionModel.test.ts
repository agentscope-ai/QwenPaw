import assert from "node:assert/strict";
import test from "node:test";

import {
  platformRefreshModes,
  platformRefreshRequest,
} from "./platformSessionModel";

test("routes web and CLI sessions to their matching refresh contracts", () => {
  assert.deepEqual(platformRefreshRequest("web", "web-token"), {
    path: "/api/v1/auth/refresh",
    body: { refreshToken: "web-token" },
  });
  assert.deepEqual(platformRefreshRequest("cli", "cli-token"), {
    path: "/api/cli/v1/auth/refresh",
    body: { refresh_token: "cli-token" },
  });
});

test("migrates legacy sessions by trying web then CLI refresh", () => {
  assert.deepEqual(platformRefreshModes(), ["web", "cli"]);
  assert.deepEqual(platformRefreshModes("cli"), ["cli"]);
});
