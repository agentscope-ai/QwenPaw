import assert from "node:assert/strict";
import test from "node:test";

import type { ChatSpec, Connection } from "../api/types";
import {
  markActivityRead,
  reconcileChatActivity,
  resolveChatActivity,
} from "./chatActivityModel";

const connection: Connection = {
  baseUrl: "http://127.0.0.1:8088",
  token: "token",
  username: "user",
  agentId: "default",
  source: "private",
};
const chat: ChatSpec = {
  id: "chat",
  session_id: "session",
  user_id: "mobile",
  channel: "console",
  name: "New Chat",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  status: "idle",
};

test("new empty chats start idle", () => {
  const activity = reconcileChatActivity({}, connection, [chat]);
  assert.equal(resolveChatActivity(connection, chat, activity), "idle");
});

test("a running chat becomes unread when it completes", () => {
  const running = { ...chat, status: "running" as const };
  const first = reconcileChatActivity({}, connection, [running]);
  const completed = {
    ...chat,
    updated_at: "2026-01-01T00:01:00Z",
  };
  const second = reconcileChatActivity(first, connection, [completed]);

  assert.equal(resolveChatActivity(connection, completed, second), "unread");
});

test("opening a completed chat marks it read", () => {
  const running = { ...chat, status: "running" as const };
  const first = reconcileChatActivity({}, connection, [running]);
  const completed = { ...chat, updated_at: "2026-01-01T00:01:00Z" };
  const unread = reconcileChatActivity(first, connection, [completed]);
  const read = markActivityRead(unread, connection, completed, true);

  assert.equal(resolveChatActivity(connection, completed, read), "read");
});
