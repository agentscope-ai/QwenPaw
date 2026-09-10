import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeApprovalLevel,
  normalizeModelOverride,
  sessionControlsKey,
} from "./sessionControlsModel";

const connection = {
  baseUrl: "http://127.0.0.1:8088",
  token: "token",
  username: "ray",
  agentId: "agent-one",
  source: "private" as const,
};

test("session control keys isolate QwenPaw, agent, and session", () => {
  const first = sessionControlsKey(connection, { id: "chat", session_id: "one" });
  const second = sessionControlsKey(
    { ...connection, agentId: "agent-two" },
    { id: "chat", session_id: "one" },
  );
  const third = sessionControlsKey(connection, { id: "chat", session_id: "two" });

  assert.notEqual(first, second);
  assert.notEqual(first, third);
  assert.match(first, /agent-one/);
});

test("model overrides require a provider and model", () => {
  assert.deepEqual(normalizeModelOverride({
    provider_id: "dashscope",
    model: "qwen-max",
  }), {
    provider_id: "dashscope",
    model: "qwen-max",
  });
  assert.equal(normalizeModelOverride({ provider_id: "dashscope" }), null);
  assert.equal(normalizeModelOverride({ provider_id: "", model: "qwen" }), null);
  assert.equal(normalizeModelOverride("qwen"), null);
});

test("approval levels normalize invalid backend values to AUTO", () => {
  assert.equal(normalizeApprovalLevel("STRICT"), "STRICT");
  assert.equal(normalizeApprovalLevel("smart"), "SMART");
  assert.equal(normalizeApprovalLevel("unknown"), "AUTO");
  assert.equal(normalizeApprovalLevel(undefined), "AUTO");
});
