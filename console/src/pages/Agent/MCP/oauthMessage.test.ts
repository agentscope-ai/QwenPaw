import { describe, expect, it } from "vitest";
import {
  getOAuthSessionTerminal,
  isOAuthSessionComplete,
  matchesOAuthMessage,
} from "./oauthMessage";

const context = {
  origin: "https://console.example",
  sessionId: "session-1",
  clientKey: "remote",
  agentId: "agent-a",
};

describe("matchesOAuthMessage", () => {
  it("accepts the current same-origin OAuth completion", () => {
    expect(
      matchesOAuthMessage(
        {
          origin: context.origin,
          data: {
            type: "mcp-oauth-success",
            session_id: context.sessionId,
            client_key: context.clientKey,
            agent_id: context.agentId,
          },
        },
        context,
      ),
    ).toBe(true);
  });

  it.each([
    ["other origin", { origin: "https://evil.example" }],
    ["stale session", { data: { session_id: "session-old" } }],
    ["other client", { data: { client_key: "other" } }],
    ["other agent", { data: { agent_id: "agent-b" } }],
  ])("rejects %s", (_name, patch) => {
    const event = {
      origin: context.origin,
      data: {
        type: "mcp-oauth-success",
        session_id: context.sessionId,
        client_key: context.clientKey,
        agent_id: context.agentId,
      },
      ...patch,
    };
    if ("data" in patch) event.data = { ...event.data, ...patch.data };
    expect(matchesOAuthMessage(event, context)).toBe(false);
  });
});

it("does not treat an old authorized token as completion of a new session", () => {
  expect(
    isOAuthSessionComplete(
      { authorized: true, session_id: "session-old", status: "completed" },
      "session-new",
    ),
  ).toBe(false);
  expect(
    isOAuthSessionComplete(
      { authorized: true, session_id: "session-new", status: "pending" },
      "session-new",
    ),
  ).toBe(false);
});

it.each([
  ["failed", false, "failed"],
  ["expired", false, "expired"],
  ["completed", false, "failed"],
  ["pending", false, null],
  ["completed", true, "success"],
])("maps %s authorized=%s to terminal %s", (status, authorized, expected) => {
  expect(
    getOAuthSessionTerminal(
      { session_id: "session-1", status, authorized },
      "session-1",
    ),
  ).toBe(expected);
});
