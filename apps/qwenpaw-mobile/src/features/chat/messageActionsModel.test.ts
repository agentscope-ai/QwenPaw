import assert from "node:assert/strict";
import test from "node:test";

import { messageText } from "./messageActionsModel";

test("collects all text parts for copy and selection", () => {
  assert.equal(messageText([
    { type: "text", text: "First paragraph" },
    { type: "image", url: "/preview.png" },
    { type: "text", text: " Second paragraph " },
  ]), "First paragraph\n\nSecond paragraph");
});

test("returns an empty string for media-only messages", () => {
  assert.equal(messageText([
    { type: "file", url: "/result.txt", name: "result.txt" },
  ]), "");
});
