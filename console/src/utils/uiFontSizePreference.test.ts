import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyUiFontSizeToRoot,
  clampUiFontSize,
  getUiFontSize,
  setUiFontSize,
  subscribeUiFontSize,
  UI_FONT_SIZE_DEFAULT,
  UI_FONT_SIZE_MAX,
  UI_FONT_SIZE_MIN,
} from "./uiFontSizePreference";

const STORAGE_KEY = "qwenpaw_ui_font_size";

function expectedPercent(size: number): string {
  const percent = Math.round((size / UI_FONT_SIZE_DEFAULT) * 100 * 1000) / 1000;
  return `${percent}%`;
}

function expectedScale(size: number): string {
  return String(Math.round((size / UI_FONT_SIZE_DEFAULT) * 1000) / 1000);
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.style.removeProperty("font-size");
  document.documentElement.style.removeProperty("--app-font-scale");
});

describe("clampUiFontSize", () => {
  it("caps the user setting at 20px", () => {
    expect(UI_FONT_SIZE_MAX).toBe(20);
  });

  it("keeps values inside the supported range", () => {
    expect(clampUiFontSize(UI_FONT_SIZE_MIN - 5)).toBe(UI_FONT_SIZE_MIN);
    expect(clampUiFontSize(UI_FONT_SIZE_MAX + 5)).toBe(UI_FONT_SIZE_MAX);
    expect(clampUiFontSize(16)).toBe(16);
  });

  it("rounds fractional input to the nearest integer", () => {
    expect(clampUiFontSize(15.6)).toBe(16);
  });

  it("falls back to the default for non-finite input", () => {
    expect(clampUiFontSize(Number.NaN)).toBe(UI_FONT_SIZE_DEFAULT);
    expect(clampUiFontSize(Number.POSITIVE_INFINITY)).toBe(
      UI_FONT_SIZE_DEFAULT,
    );
  });
});

describe("get/set persistence", () => {
  it("returns the default when nothing is stored", () => {
    expect(getUiFontSize()).toBe(UI_FONT_SIZE_DEFAULT);
  });

  it("persists and reads back a non-default size", () => {
    setUiFontSize(18);
    expect(getUiFontSize()).toBe(18);
  });

  it("removes the key when set back to the default", () => {
    setUiFontSize(18);
    setUiFontSize(UI_FONT_SIZE_DEFAULT);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(getUiFontSize()).toBe(UI_FONT_SIZE_DEFAULT);
  });

  it("clamps out-of-range values before storing", () => {
    setUiFontSize(999);
    expect(getUiFontSize()).toBe(UI_FONT_SIZE_MAX);
  });
});

describe("subscribeUiFontSize", () => {
  it("notifies subscribers on change and stops after unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeUiFontSize(listener);
    setUiFontSize(20);
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    setUiFontSize(16);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("applyUiFontSizeToRoot", () => {
  it("resolves to 100% / scale 1 at the default size", () => {
    applyUiFontSizeToRoot(UI_FONT_SIZE_DEFAULT);
    const root = document.documentElement;
    expect(root.style.fontSize).toBe("100%");
    expect(root.style.getPropertyValue("--app-font-scale")).toBe("1");
  });

  it("scales proportionally for larger sizes", () => {
    applyUiFontSizeToRoot(UI_FONT_SIZE_MAX);
    const root = document.documentElement;
    expect(root.style.fontSize).toBe(expectedPercent(UI_FONT_SIZE_MAX));
    expect(root.style.getPropertyValue("--app-font-scale")).toBe(
      expectedScale(UI_FONT_SIZE_MAX),
    );
  });

  it("clamps before applying", () => {
    applyUiFontSizeToRoot(999);
    expect(document.documentElement.style.fontSize).toBe(
      expectedPercent(UI_FONT_SIZE_MAX),
    );
  });
});
