import { describe, expect, it } from "vitest";
import {
  accumulateOffsets,
  computeSpacers,
  expandIndexRange,
  getVisibleIndexRange,
  isAtNewestEdge,
  isNearOldestEdge,
  itemKey,
  newestEdgeGrowthPx,
  preserveReverseAnchorScrollTop,
  reverseAnchorAt,
  reverseViewWindow,
  scrollTopForIndex,
  scrollTopForReverseAnchor,
} from "./range";

describe("itemKey", () => {
  it("prefers id over key over index", () => {
    expect(itemKey({ id: "a", key: "k" }, 3)).toBe("a");
    expect(itemKey({ key: "k" }, 3)).toBe("k");
    expect(itemKey({}, 3)).toBe("idx-3");
  });
});

describe("accumulateOffsets", () => {
  it("stacks measured heights with gaps from the newest edge", () => {
    const heights = new Map([
      ["n0", 100],
      ["n1", 50],
    ]);
    const { offsets, sizes, total } = accumulateOffsets(
      ["n0", "n1", "n2"],
      heights,
      80,
      24,
    );
    expect(sizes).toEqual([100, 50, 80]);
    expect(offsets).toEqual([0, 124, 198]);
    expect(total).toBe(278);
  });
});

describe("reverseViewWindow / getVisibleIndexRange", () => {
  it("only covers the viewport plus overscan", () => {
    const { offsets, sizes } = accumulateOffsets(
      Array.from({ length: 20 }, (_, i) => `n${i}`),
      new Map(),
      100,
      0,
    );
    const { viewStart, viewEnd } = reverseViewWindow(0, 250, 50);
    expect(viewStart).toBe(0);
    expect(viewEnd).toBe(300);
    const { start, end } = getVisibleIndexRange(
      offsets,
      sizes,
      viewStart,
      viewEnd,
    );
    expect(start).toBe(0);
    expect(end).toBeLessThan(19);
    expect(end).toBeGreaterThanOrEqual(2);
  });

  it("moves the window toward older items as scrollTop goes negative", () => {
    const { offsets, sizes } = accumulateOffsets(
      Array.from({ length: 20 }, (_, i) => `n${i}`),
      new Map(),
      100,
      0,
    );
    const { viewStart, viewEnd } = reverseViewWindow(-800, 200, 0);
    const { start, end } = getVisibleIndexRange(
      offsets,
      sizes,
      viewStart,
      viewEnd,
    );
    expect(start).toBeGreaterThan(0);
    expect(end).toBeLessThan(19);
  });
});

describe("computeSpacers", () => {
  it("pads unmounted newer and older rows", () => {
    const { offsets, sizes, total } = accumulateOffsets(
      ["a", "b", "c", "d"],
      new Map(),
      100,
      0,
    );
    expect(computeSpacers(1, 2, offsets, sizes, total)).toEqual({
      startSpacer: 100,
      endSpacer: 100,
    });
  });
});

describe("scroll edges", () => {
  it("treats scrollTop ~ 0 as the newest edge", () => {
    expect(isAtNewestEdge(0)).toBe(true);
    expect(isAtNewestEdge(-40)).toBe(false);
  });

  it("detects the oldest edge of a reverse scroller", () => {
    expect(isNearOldestEdge(-920, 1200, 200, 80)).toBe(true);
    expect(isNearOldestEdge(-100, 1200, 200, 80)).toBe(false);
    expect(isNearOldestEdge(0, 200, 200, 80)).toBe(false);
  });

  it("places an index at the oldest edge of the viewport", () => {
    const { offsets, sizes } = accumulateOffsets(
      ["a", "b", "c"],
      new Map(),
      100,
      0,
    );
    expect(scrollTopForIndex(2, offsets, sizes, 150, "oldest")).toBe(-150);
  });
});

describe("expandIndexRange", () => {
  it("adds extra rows on both sides without leaving the list", () => {
    expect(expandIndexRange(4, 6, 10, 3)).toEqual({ start: 1, end: 9 });
    expect(expandIndexRange(0, 1, 5, 3)).toEqual({ start: 0, end: 4 });
    expect(expandIndexRange(0, -1, 0, 3)).toEqual({ start: 0, end: -1 });
  });
});

describe("newestEdgeGrowthPx / preserveReverseAnchorScrollTop", () => {
  it("measures inserted rows in front of the previous newest id", () => {
    const { offsets } = accumulateOffsets(
      ["live", "n0", "n1"],
      new Map(),
      100,
      0,
    );
    expect(
      newestEdgeGrowthPx("n0", ["live", "n0", "n1"], offsets, 100, 100),
    ).toBe(100);
  });

  it("measures streaming growth of the same newest row", () => {
    expect(newestEdgeGrowthPx("n0", ["n0", "n1"], [0, 140], 100, 140)).toBe(40);
  });

  it("pins to the newest edge when the user is already there", () => {
    expect(preserveReverseAnchorScrollTop(-12, true, 80)).toBe(0);
  });

  it("moves scrollTop with newest-edge growth so the anchor does not jump", () => {
    expect(preserveReverseAnchorScrollTop(-320, false, 100)).toBe(-420);
    expect(preserveReverseAnchorScrollTop(-240, false, 0)).toBe(-240);
  });

  it("restores the same row after older messages are prepended", () => {
    const keysBefore = ["n20", "n19", "n18"];
    const before = accumulateOffsets(keysBefore, new Map(), 100, 0);
    const keysAfter = ["n20", "n19", "n18", "n17", "n16"];
    const after = accumulateOffsets(keysAfter, new Map(), 100, 0);
    const anchor = reverseAnchorAt(
      240,
      keysBefore,
      before.offsets,
      before.sizes,
    );
    expect(anchor).toEqual({ key: "n18", offsetInItem: 40 });
    expect(scrollTopForReverseAnchor(anchor!, keysAfter, after.offsets)).toBe(
      -240,
    );
  });

  it("shifts scrollTop when a new row is inserted at the newest edge", () => {
    const keysBefore = Array.from({ length: 20 }, (_, index) => `n${index}`);
    const before = accumulateOffsets(keysBefore, new Map(), 100, 0);
    const keysAfter = ["live", ...keysBefore];
    const after = accumulateOffsets(keysAfter, new Map(), 100, 0);
    const anchor = reverseAnchorAt(
      320,
      keysBefore,
      before.offsets,
      before.sizes,
    );
    expect(scrollTopForReverseAnchor(anchor!, keysAfter, after.offsets)).toBe(
      -420,
    );
  });
});
