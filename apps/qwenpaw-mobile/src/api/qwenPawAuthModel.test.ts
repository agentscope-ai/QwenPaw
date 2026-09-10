import assert from "node:assert/strict";
import test from "node:test";

import {
  qwenPawCredentialEndpoint,
  requiresQwenPawCredentials,
  shouldBootstrapHub,
} from "./qwenPawAuthModel";

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

test("Hub always requires an identity and exposes bootstrap state", () => {
  const status = {
    bootstrap_required: true,
    enabled: true,
    has_users: false,
    mode: "hub" as const,
  };
  assert.equal(requiresQwenPawCredentials(status), true);
  assert.equal(shouldBootstrapHub(status), true);
  assert.equal(qwenPawCredentialEndpoint(status), "/api/auth/register");
  assert.equal(qwenPawCredentialEndpoint({
    ...status,
    bootstrap_required: false,
  }), "/api/auth/login");
});
