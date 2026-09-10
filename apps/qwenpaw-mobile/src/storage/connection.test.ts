import assert from "node:assert/strict";
import test from "node:test";

import {
  connectionKey,
  findConnectionByBaseUrl,
  upsertConnection,
  withoutConnection,
} from "./connectionModel";

const local = {
  baseUrl: "http://127.0.0.1:8088/",
  token: "local-token",
  username: "local",
  agentId: "default",
  source: "private" as const,
};
const platform = {
  baseUrl: "https://paw.example.com",
  token: "platform-token",
  username: "cloud",
  agentId: "default",
  source: "platform" as const,
};

test("connectionKey is stable across trailing slashes", () => {
  assert.equal(connectionKey(local), "private:http://127.0.0.1:8088");
});

test("findConnectionByBaseUrl reuses only the matching source", () => {
  assert.equal(
    findConnectionByBaseUrl([local, platform], "platform", "https://paw.example.com/"),
    platform,
  );
  assert.equal(
    findConnectionByBaseUrl([local], "platform", local.baseUrl),
    null,
  );
});

test("upsertConnection keeps both workspace bindings", () => {
  const first = upsertConnection({ activeKey: null, connections: [] }, local);
  const second = upsertConnection(first, platform);

  assert.equal(second.connections.length, 2);
  assert.equal(second.activeKey, connectionKey(platform));
});

test("withoutConnection activates the remaining workspace", () => {
  const registry = upsertConnection(
    upsertConnection({ activeKey: null, connections: [] }, local),
    platform,
  );
  const next = withoutConnection(registry, connectionKey(platform));

  assert.deepEqual(next.connections, [local]);
  assert.equal(next.activeKey, connectionKey(local));
});
