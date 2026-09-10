import assert from "node:assert/strict";
import test from "node:test";

import { mobileLanguage, mobileText } from "./locale";

test("keeps the current Chinese catalog consistent across screens", () => {
  assert.equal(mobileLanguage, "zh");
  assert.equal(mobileText("会话", "Chats"), "会话");
});
