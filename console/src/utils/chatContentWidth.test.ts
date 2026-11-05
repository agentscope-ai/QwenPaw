import { beforeEach, describe, expect, it } from "vitest";
import {
  CHAT_CONTENT_WIDTH_DEFAULT,
  CHAT_CONTENT_WIDTH_EDGE_BUDGET,
  CHAT_CONTENT_WIDTH_HANDLE_GAP,
  CHAT_CONTENT_WIDTH_HANDLE_WIDTH,
  CHAT_CONTENT_WIDTH_MIN,
  CHAT_CONTENT_WIDTH_MIN_SPARE,
  CHAT_CONTENT_WIDTH_STORAGE_KEY,
  canResizeChatContent,
  clampChatContentWidth,
  contentWidthFromHandleOffset,
  maxChatContentWidth,
  readChatContentWidthPreference,
  resolveChatContentWidth,
  writeChatContentWidthPreference,
} from "./chatContentWidth";

beforeEach(() => {
  localStorage.clear();
});

describe("chat content width preference storage", () => {
  it("returns null when no preference was stored", () => {
    expect(readChatContentWidthPreference()).toBeNull();
  });

  it("round-trips a persisted width", () => {
    writeChatContentWidthPreference(812.4);
    expect(localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY)).toBe("812");
    expect(readChatContentWidthPreference()).toBe(812);
  });

  it("clears the preference when written with null", () => {
    writeChatContentWidthPreference(700);
    writeChatContentWidthPreference(null);
    expect(localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY)).toBeNull();
    expect(readChatContentWidthPreference()).toBeNull();
  });

  it("ignores corrupt or non-positive stored values", () => {
    localStorage.setItem(CHAT_CONTENT_WIDTH_STORAGE_KEY, "wide");
    expect(readChatContentWidthPreference()).toBeNull();
    localStorage.setItem(CHAT_CONTENT_WIDTH_STORAGE_KEY, "-40");
    expect(readChatContentWidthPreference()).toBeNull();
    localStorage.setItem(CHAT_CONTENT_WIDTH_STORAGE_KEY, "0");
    expect(readChatContentWidthPreference()).toBeNull();
  });
});

describe("chat content width range", () => {
  it("keeps the shipped width before the first drag", () => {
    expect(resolveChatContentWidth(1600, null)).toBe(
      CHAT_CONTENT_WIDTH_DEFAULT,
    );
    expect(resolveChatContentWidth(720, null)).toBe(720);
  });

  it("reserves the handle edge budget above the floor", () => {
    expect(maxChatContentWidth(1600)).toBe(
      1600 - CHAT_CONTENT_WIDTH_EDGE_BUDGET,
    );
    expect(maxChatContentWidth(400)).toBe(CHAT_CONTENT_WIDTH_MIN);
  });

  it("clamps a requested width into the draggable range", () => {
    expect(clampChatContentWidth(120, 1600)).toBe(CHAT_CONTENT_WIDTH_MIN);
    expect(clampChatContentWidth(9999, 1600)).toBe(
      1600 - CHAT_CONTENT_WIDTH_EDGE_BUDGET,
    );
    expect(clampChatContentWidth(800, 1600)).toBe(800);
  });

  it("clamps a stored preference when resolving the rendered width", () => {
    expect(resolveChatContentWidth(1600, 5000)).toBe(
      1600 - CHAT_CONTENT_WIDTH_EDGE_BUDGET,
    );
    expect(resolveChatContentWidth(1600, 100)).toBe(CHAT_CONTENT_WIDTH_MIN);
  });

  it("doubles a symmetric handle offset into the column width", () => {
    expect(contentWidthFromHandleOffset(960, 40, 1600)).toBe(1040);
    expect(contentWidthFromHandleOffset(960, -40, 1600)).toBe(880);
    expect(contentWidthFromHandleOffset(960, 500, 1600)).toBe(
      1600 - CHAT_CONTENT_WIDTH_EDGE_BUDGET,
    );
  });

  it("only offers handles when the column leaves spare room for them", () => {
    expect(canResizeChatContent(1600, 960)).toBe(true);
    expect(
      canResizeChatContent(960 + CHAT_CONTENT_WIDTH_MIN_SPARE * 2, 960),
    ).toBe(true);
    expect(canResizeChatContent(960, 960)).toBe(false);
    expect(canResizeChatContent(800, 800)).toBe(false);
  });

  it("keeps a comfortable pointer target around the thin visual line", () => {
    expect(CHAT_CONTENT_WIDTH_HANDLE_GAP).toBe(16);
    expect(CHAT_CONTENT_WIDTH_HANDLE_WIDTH).toBe(28);
    expect(CHAT_CONTENT_WIDTH_MIN_SPARE).toBe(48);
  });
});
