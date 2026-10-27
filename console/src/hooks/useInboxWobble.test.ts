// @vitest-environment jsdom
// Tests for the shared "approval wobble" toggle hook.
//
// The hook has no existing test file; pages/Inbox/index.test.tsx only exercises
// it indirectly through the page, which leaves the hook body itself uncovered.
// The contract asserted here is the one the hook documents: persisted in
// localStorage, enabled by default, and cross-component synchronised through a
// CustomEvent on window.
//
// Environment facts relied on (probed locally, not assumed):
//   - src/test/setup.ts replaces localStorage with a vi.fn()-backed store whose
//     getItem is `store[key] || null`, so storing "" reads back as null.
//   - window.dispatchEvent(new CustomEvent(name)) is synchronous in jsdom, so a
//     listener registered by a second hook instance runs before the assertion.
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useInboxWobble } from "./useInboxWobble";

const STORAGE_KEY = "qwenpaw.inbox.approvalWobble";
const SYNC_EVENT = "qwenpaw:inbox-wobble-change";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("useInboxWobble - initial value", () => {
  it("defaults to enabled when nothing was persisted yet", () => {
    const { result } = renderHook(() => useInboxWobble());
    expect(result.current[0]).toBe(true);
  });

  it("reads a persisted opt-out as disabled", () => {
    localStorage.setItem(STORAGE_KEY, "false");
    const { result } = renderHook(() => useInboxWobble());
    expect(result.current[0]).toBe(false);
  });

  it("reads a persisted opt-in as enabled", () => {
    localStorage.setItem(STORAGE_KEY, "true");
    const { result } = renderHook(() => useInboxWobble());
    expect(result.current[0]).toBe(true);
  });

  it("treats any value other than the exact string false as enabled", () => {
    localStorage.setItem(STORAGE_KEY, "0");
    expect(renderHook(() => useInboxWobble()).result.current[0]).toBe(true);

    localStorage.setItem(STORAGE_KEY, "FALSE");
    expect(renderHook(() => useInboxWobble()).result.current[0]).toBe(true);
  });
});

describe("useInboxWobble - toggle", () => {
  it("persists the opt-out and flips the returned flag", () => {
    const { result } = renderHook(() => useInboxWobble());

    act(() => {
      result.current[1]();
    });

    expect(result.current[0]).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("false");
  });

  it("persists the opt-in when toggled back from a stored opt-out", () => {
    localStorage.setItem(STORAGE_KEY, "false");
    const { result } = renderHook(() => useInboxWobble());
    expect(result.current[0]).toBe(false);

    act(() => {
      result.current[1]();
    });

    expect(result.current[0]).toBe(true);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("true");
  });

  it("returns to the original flag after two toggles", () => {
    const { result } = renderHook(() => useInboxWobble());

    act(() => {
      result.current[1]();
    });
    expect(result.current[0]).toBe(false);

    act(() => {
      result.current[1]();
    });
    expect(result.current[0]).toBe(true);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("true");
  });

  it("derives the next value from storage rather than from stale state", () => {
    // Storage says opt-out while the hook still reports the default enabled, so
    // a toggle must flip storage to "true" instead of writing "false" again.
    localStorage.setItem(STORAGE_KEY, "false");
    const { result } = renderHook(() => useInboxWobble());
    localStorage.setItem(STORAGE_KEY, "true");

    act(() => {
      result.current[1]();
    });

    // Storage held "true", so the toggle writes the opposite: "false".
    expect(localStorage.getItem(STORAGE_KEY)).toBe("false");
    expect(result.current[0]).toBe(false);
  });

  it("hands back a stable toggle function across renders", () => {
    const { result, rerender } = renderHook(() => useInboxWobble());
    const first = result.current[1];

    rerender();
    expect(result.current[1]).toBe(first);
  });
});

describe("useInboxWobble - cross-component sync", () => {
  it("publishes the sync event on every toggle", () => {
    const listener = vi.fn();
    window.addEventListener(SYNC_EVENT, listener);
    const { result } = renderHook(() => useInboxWobble());

    act(() => {
      result.current[1]();
    });
    expect(listener).toHaveBeenCalledTimes(1);

    act(() => {
      result.current[1]();
    });
    expect(listener).toHaveBeenCalledTimes(2);

    window.removeEventListener(SYNC_EVENT, listener);
  });

  it("propagates a toggle to a second mounted instance", () => {
    const first = renderHook(() => useInboxWobble());
    const second = renderHook(() => useInboxWobble());
    expect(second.result.current[0]).toBe(true);

    act(() => {
      first.result.current[1]();
    });

    expect(first.result.current[0]).toBe(false);
    expect(second.result.current[0]).toBe(false);

    act(() => {
      second.result.current[1]();
    });
    expect(second.result.current[0]).toBe(true);
    expect(first.result.current[0]).toBe(true);
  });

  it("picks up a storage change made outside the hook when the event fires", () => {
    const { result } = renderHook(() => useInboxWobble());
    expect(result.current[0]).toBe(true);

    act(() => {
      localStorage.setItem(STORAGE_KEY, "false");
      window.dispatchEvent(new CustomEvent(SYNC_EVENT));
    });
    expect(result.current[0]).toBe(false);

    act(() => {
      localStorage.removeItem(STORAGE_KEY);
      window.dispatchEvent(new CustomEvent(SYNC_EVENT));
    });
    expect(result.current[0]).toBe(true);
  });

  it("ignores the sync event once unmounted", () => {
    const { result, unmount } = renderHook(() => useInboxWobble());
    const spy = vi.spyOn(window, "removeEventListener");

    unmount();
    expect(spy).toHaveBeenCalledWith(SYNC_EVENT, expect.any(Function));

    // Firing the event after unmount must not throw (no update on a dead hook).
    expect(() => {
      act(() => {
        window.dispatchEvent(new CustomEvent(SYNC_EVENT));
      });
    }).not.toThrow();
    expect(result.current[0]).toBe(true);
  });

  it("keeps a surviving instance in sync after its sibling unmounts", () => {
    const first = renderHook(() => useInboxWobble());
    const second = renderHook(() => useInboxWobble());

    second.unmount();

    act(() => {
      first.result.current[1]();
    });
    expect(first.result.current[0]).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("false");
  });
});
