import assert from "node:assert/strict";
import test from "node:test";

import { placeAnchoredMenu } from "./anchoredMenuModel";

const base = {
  bottomInset: 20,
  gap: 10,
  margin: 12,
  menuHeight: 76,
  menuWidth: 176,
  topInset: 47,
  viewportHeight: 812,
  viewportWidth: 375,
};

test("places a centered menu above its message bubble", () => {
  assert.deepEqual(placeAnchoredMenu({
    ...base,
    anchor: { x: 120, y: 420, width: 140, height: 52 },
  }), {
    above: true,
    arrowLeft: 82,
    left: 102,
    top: 334,
  });
});

test("keeps the menu inside the left screen gutter", () => {
  const placement = placeAnchoredMenu({
    ...base,
    anchor: { x: 4, y: 420, width: 48, height: 52 },
  });

  assert.equal(placement.left, 12);
  assert.equal(placement.arrowLeft, 14);
});

test("places the menu below when there is not enough room above", () => {
  const placement = placeAnchoredMenu({
    ...base,
    anchor: { x: 120, y: 70, width: 140, height: 52 },
  });

  assert.equal(placement.above, false);
  assert.equal(placement.top, 132);
});

test("uses the keyboard-reduced viewport to avoid the lower edge", () => {
  const placement = placeAnchoredMenu({
    ...base,
    anchor: { x: 120, y: 310, width: 140, height: 52 },
    viewportHeight: 420,
  });

  assert.equal(placement.above, true);
  assert.equal(placement.top, 224);
});
