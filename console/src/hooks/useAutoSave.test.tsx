import { act, renderHook } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
const feedback = vi.hoisted(() => ({ error: vi.fn(), destroy: vi.fn() }));
vi.mock("./useAppMessage", () => ({
  useAppMessage: () => ({ message: feedback }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
import { useAutoSave } from "./useAutoSave";

describe("settings autosave", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });
  afterEach(() => vi.useRealTimers());
  it("coalesces edits and saves the latest committed value", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result, rerender, unmount } = renderHook(
      ({ value }) => useAutoSave(() => save(value)),
      { initialProps: { value: 1 } },
    );
    act(() => result.current.schedule());
    await act(() => vi.advanceTimersByTimeAsync(600));
    rerender({ value: 2 });
    act(() => result.current.schedule());
    await act(() => vi.advanceTimersByTimeAsync(999));
    expect(save).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(save).toHaveBeenCalledExactlyOnceWith(2);
    unmount();
  });
  it("flushes when leaving and never saves a page with no edits", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const a = renderHook(() => useAutoSave(save));
    a.unmount();
    expect(save).not.toHaveBeenCalled();
    const b = renderHook(() => useAutoSave(save));
    act(() => b.result.current.schedule());
    b.unmount();
    await act(async () => {});
    expect(save).toHaveBeenCalledTimes(1);
  });
  it("serializes a newer edit behind an in-flight write", async () => {
    let resolve!: () => void;
    const save = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<void>((r) => {
            resolve = r;
          }),
      )
      .mockResolvedValue(undefined);
    const { result, unmount } = renderHook(() => useAutoSave(save));
    act(() => result.current.schedule());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    act(() => result.current.schedule());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => resolve());
    expect(save).toHaveBeenCalledTimes(2);
    unmount();
  });
  it("retains a retry action when a write fails", async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(undefined);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { result, unmount } = renderHook(() => useAutoSave(save));
    act(() => result.current.schedule());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(feedback.error).toHaveBeenCalledWith(
      expect.objectContaining({ duration: 0 }),
    );
    unmount();
  });
});
