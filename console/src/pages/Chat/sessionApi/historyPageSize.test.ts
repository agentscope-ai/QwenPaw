import { afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_HISTORY_PAGE_SIZE,
  HISTORY_PAGE_SIZE_MAX,
  HISTORY_PAGE_SIZE_MIN,
  HISTORY_PAGE_SIZE_STORAGE_KEY,
  clampHistoryPageSize,
  commitHistoryPageSize,
  getHistoryPageSize,
  parseHistoryPageSize,
  resetHistoryPageSizeForTests,
  setHistoryPageSize,
} from "./historyPageSize";

describe("history page size preference", () => {
  afterEach(() => {
    resetHistoryPageSizeForTests();
  });

  it("defaults to 50 when nothing is stored", () => {
    expect(getHistoryPageSize()).toBe(DEFAULT_HISTORY_PAGE_SIZE);
  });

  it("parses numbers and rejects empty or garbage", () => {
    expect(parseHistoryPageSize(200)).toBe(200);
    expect(parseHistoryPageSize("80")).toBe(80);
    expect(parseHistoryPageSize("")).toBeNull();
    expect(parseHistoryPageSize("   ")).toBeNull();
    expect(parseHistoryPageSize(null)).toBeNull();
    expect(parseHistoryPageSize(undefined)).toBeNull();
    expect(parseHistoryPageSize("nope")).toBeNull();
    expect(parseHistoryPageSize(true)).toBeNull();
  });

  it("clamps to the backend limit contract", () => {
    expect(clampHistoryPageSize(0)).toBe(HISTORY_PAGE_SIZE_MIN);
    expect(clampHistoryPageSize(-12)).toBe(HISTORY_PAGE_SIZE_MIN);
    expect(clampHistoryPageSize(50.9)).toBe(50);
    expect(clampHistoryPageSize(99999)).toBe(HISTORY_PAGE_SIZE_MAX);
  });

  it("persists a valid size and reads it back", () => {
    expect(setHistoryPageSize(200)).toEqual({ value: 200, changed: true });
    expect(getHistoryPageSize()).toBe(200);
    expect(localStorage.getItem(HISTORY_PAGE_SIZE_STORAGE_KEY)).toBe("200");
    expect(setHistoryPageSize(200).changed).toBe(false);
  });

  it("commit restores nothing on garbage and clamps out-of-range numbers", () => {
    setHistoryPageSize(50);
    expect(commitHistoryPageSize("")).toBeNull();
    expect(commitHistoryPageSize("abc")).toBeNull();
    expect(getHistoryPageSize()).toBe(50);
    expect(commitHistoryPageSize(0)).toEqual({
      value: HISTORY_PAGE_SIZE_MIN,
      changed: true,
    });
    expect(getHistoryPageSize()).toBe(HISTORY_PAGE_SIZE_MIN);
  });

  it("treats garbage already in storage as the default", () => {
    resetHistoryPageSizeForTests();
    localStorage.setItem(HISTORY_PAGE_SIZE_STORAGE_KEY, "nope");
    expect(getHistoryPageSize()).toBe(DEFAULT_HISTORY_PAGE_SIZE);
  });
});
