import assert from "node:assert/strict";
import test from "node:test";

import { moduleSnapshotItems, summarizeModulePayload } from "./summary";

test("summarizeModulePayload reports arrays and object fields", () => {
  assert.equal(summarizeModulePayload([1, 2, 3]), "3 项");
  assert.equal(summarizeModulePayload({ enabled: true, mode: "strict" }), "2 个配置字段");
  assert.equal(summarizeModulePayload({ agents: [1, 2] }), "2 项");
});

test("moduleSnapshotItems formats collections without exposing secrets", () => {
  assert.deepEqual(moduleSnapshotItems([
    { name: "web_search", enabled: true, api_key: "hidden" },
  ]), [{
    id: "web_search-0",
    title: "web_search",
    subtitle: "Enabled · 已启用",
  }]);
  assert.deepEqual(moduleSnapshotItems({
    enabled: true,
    api_token: "hidden",
  }), [{ id: "enabled", title: "Enabled", subtitle: "已启用" }]);
});
