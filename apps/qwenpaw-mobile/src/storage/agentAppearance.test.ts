import assert from "node:assert/strict";
import test from "node:test";

import type { AgentSummary, Connection } from "../api/types";
import { agentAppearanceKey, resolveAgentAppearance } from "./agentAppearance";

const connection: Connection = {
  baseUrl: "http://127.0.0.1:8088/",
  token: "",
  username: "",
  agentId: "default",
};
const agent: AgentSummary = {
  id: "default",
  name: "Default",
  description: "",
  enabled: true,
  available_in_chat: true,
  startup_status: "running",
};

test("agent appearance is scoped by server and agent id", () => {
  const key = agentAppearanceKey(connection.baseUrl, agent.id);
  assert.deepEqual(resolveAgentAppearance({
    [key]: { nickname: "小爪", avatarUri: "file:///avatar.png" },
  }, connection, agent), {
    name: "小爪",
    avatarUri: "file:///avatar.png",
  });
});
