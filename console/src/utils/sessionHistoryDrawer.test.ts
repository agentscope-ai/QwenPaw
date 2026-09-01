import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  OPEN_SESSION_HISTORY_DRAWER_EVENT,
  requestSessionHistoryDrawerOpen,
  SESSION_HISTORY_DRAWER_STORAGE_KEY,
} from "./sessionHistoryDrawer";

describe("sessionHistoryDrawer", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("persists and dispatches a request to open the history drawer", () => {
    const listener = vi.fn();
    window.addEventListener(OPEN_SESSION_HISTORY_DRAWER_EVENT, listener);

    requestSessionHistoryDrawerOpen();

    expect(localStorage.getItem(SESSION_HISTORY_DRAWER_STORAGE_KEY)).toBe(
      "true",
    );
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener(OPEN_SESSION_HISTORY_DRAWER_EVENT, listener);
  });
});
