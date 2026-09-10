import assert from "node:assert/strict";
import test from "node:test";

import {
  hubRoleLabel,
  hubRuntimeStateLabel,
  hubRuntimeStateTone,
} from "./hubModel";

test("formats Hub runtime states for compact mobile status badges", () => {
  assert.equal(hubRuntimeStateLabel("running"), "运行中");
  assert.equal(hubRuntimeStateLabel("failed"), "异常");
  assert.equal(hubRuntimeStateLabel(null), "尚未创建");
  assert.equal(hubRuntimeStateTone("running"), "positive");
  assert.equal(hubRuntimeStateTone("starting"), "accent");
  assert.equal(hubRuntimeStateTone("stopped"), "muted");
  assert.equal(hubRuntimeStateTone("failed"), "danger");
});

test("formats Hub roles without exposing backend enum copy", () => {
  assert.equal(hubRoleLabel("admin"), "管理员");
  assert.equal(hubRoleLabel("user"), "成员");
});
