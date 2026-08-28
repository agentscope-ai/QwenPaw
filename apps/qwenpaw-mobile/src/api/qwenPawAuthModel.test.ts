import assert from "node:assert/strict";
import test from "node:test";

import { requiresQwenPawCredentials } from "./qwenPawAuthModel";

test("requires credentials only after QwenPaw has an independent user", () => {
  assert.equal(requiresQwenPawCredentials({
    enabled: false,
    has_users: false,
  }), false);
  assert.equal(requiresQwenPawCredentials({
    enabled: true,
    has_users: false,
  }), false);
  assert.equal(requiresQwenPawCredentials({
    enabled: true,
    has_users: true,
  }), true);
});
