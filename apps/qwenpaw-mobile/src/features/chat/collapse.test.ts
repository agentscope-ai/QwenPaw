import assert from "node:assert/strict";
import test from "node:test";

import { collapseTextParts } from "./collapse";

test("short answers remain unchanged", () => {
  const parts = [{ type: "text" as const, text: "short" }];
  assert.deepEqual(collapseTextParts(parts, 10), {
    collapsible: false,
    parts,
  });
});

test("long answers collapse while retaining media", () => {
  const image = { type: "image" as const, url: "/tmp/image.png" };
  const result = collapseTextParts([
    { type: "text", text: "1234567890" },
    image,
  ], 5);

  assert.equal(result.collapsible, true);
  assert.deepEqual(result.parts, [
    { type: "text", text: "12345…" },
    image,
  ]);
});
