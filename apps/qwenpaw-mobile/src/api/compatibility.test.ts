import assert from "node:assert/strict";
import test from "node:test";

import { availableAgents, isChatGroupsUnsupported } from "./compatibility";

test("detects QwenPaw builds without the chat groups route", () => {
  assert.equal(
    isChatGroupsUnsupported(new Error("Chat not found: groups")),
    true,
  );
  assert.equal(isChatGroupsUnsupported(new Error("Chat not found: other")), false);
  assert.equal(isChatGroupsUnsupported(new Error("500 Internal Server Error")), false);
});

test("keeps agents from official images that omit newer visibility flags", () => {
  const agents = availableAgents([
    { id: "default", name: "Default" },
    { id: "disabled", name: "Disabled", enabled: false },
    { id: "hidden", name: "Hidden", available_in_chat: false },
  ] as never[]);

  assert.deepEqual(agents.map((agent) => agent.id), ["default"]);
});
