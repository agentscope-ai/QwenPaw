import assert from "node:assert/strict";
import test from "node:test";

import { mapHttpRequestToRelay } from "./relayRequestModel";

test("maps chat bootstrap requests to fixed Relay operations", () => {
  assert.deepEqual(
    mapHttpRequestToRelay("/agents", "GET", undefined, "default"),
    { operation: "agent.list", payload: { agent_id: "default" } },
  );
  assert.deepEqual(
    mapHttpRequestToRelay("/chats?archived=true", "GET", undefined, "paw"),
    {
      operation: "session.list",
      payload: { agent_id: "paw", archived: true },
    },
  );
});

test("does not map arbitrary paths into the private QwenPaw network", () => {
  assert.equal(
    mapHttpRequestToRelay("/workspace/files", "GET", undefined, "default"),
    null,
  );
  assert.equal(
    mapHttpRequestToRelay(
      "https://evil.test/admin",
      "GET",
      undefined,
      "default",
    ),
    null,
  );
});

test("maps chat and group edits without exposing an arbitrary path", () => {
  assert.deepEqual(
    mapHttpRequestToRelay(
      "/chats/chat-1",
      "PUT",
      JSON.stringify({ group_id: "group-2" }),
      "default",
    ),
    {
      operation: "session.update",
      payload: {
        agent_id: "default",
        chat_id: "chat-1",
        group_id: "group-2",
      },
    },
  );
  assert.deepEqual(
    mapHttpRequestToRelay(
      "/chats/groups/group-1",
      "DELETE",
      undefined,
      "default",
    ),
    {
      operation: "session.delete",
      payload: {
        agent_id: "default",
        resource: "groups",
        target_group_id: "group-1",
      },
    },
  );
});
