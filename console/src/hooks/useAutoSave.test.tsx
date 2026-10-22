import { act, renderHook } from "@testing-library/react";
import type { ModalFuncProps } from "antd";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
const feedback = vi.hoisted(() => ({
  error: vi.fn(),
  destroy: vi.fn(),
  confirm: vi.fn(),
}));
vi.mock("./useAppMessage", () => ({
  useAppMessage: () => ({
    message: feedback,
    modal: { confirm: feedback.confirm },
  }),
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
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });
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

  it("closes an unchanged editor without saving or confirming", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    const { result } = renderHook(() => useAutoSave(save));
    await act(() => result.current.requestClose(onClose));
    expect(onClose).toHaveBeenCalledOnce();
    expect(save).not.toHaveBeenCalled();
    expect(feedback.confirm).not.toHaveBeenCalled();
  });

  it("keeps invalid edits when the user chooses to continue editing", async () => {
    const save = vi.fn().mockResolvedValue(false);
    const onClose = vi.fn();
    const { result, unmount } = renderHook(() => useAutoSave(save));
    act(() => result.current.schedule());
    let closing!: Promise<void>;
    await act(async () => {
      closing = result.current.requestClose(onClose);
    });
    expect(feedback.confirm).toHaveBeenCalledOnce();
    const confirmation = feedback.confirm.mock.calls[0][0] as ModalFuncProps;
    expect(confirmation.autoFocusButton).toBe("cancel");
    await act(async () => {
      confirmation.onCancel?.();
      await closing;
    });
    expect(onClose).not.toHaveBeenCalled();
    save.mockResolvedValue(undefined);
    await act(() => result.current.requestClose(onClose));
    expect(onClose).toHaveBeenCalledOnce();
    expect(save).toHaveBeenCalledTimes(2);
    unmount();
  });

  it("discards invalid edits without retrying on timers or unmount", async () => {
    const save = vi.fn().mockResolvedValue(false);
    const onClose = vi.fn();
    const { result, unmount } = renderHook(() => useAutoSave(save));
    act(() => result.current.schedule());
    let closing!: Promise<void>;
    await act(async () => {
      closing = result.current.requestClose(onClose);
    });
    const confirmation = feedback.confirm.mock.calls[0][0] as ModalFuncProps;
    await act(async () => {
      confirmation.onOk?.();
      await closing;
    });
    expect(onClose).toHaveBeenCalledOnce();
    await act(() => vi.advanceTimersByTimeAsync(2000));
    unmount();
    await act(async () => {});
    expect(save).toHaveBeenCalledOnce();
  });

  it("deduplicates close requests while saving and confirming", async () => {
    let finishSave!: (saved: boolean) => void;
    const save = vi
      .fn()
      .mockImplementation(
        () => new Promise<boolean>((resolve) => (finishSave = resolve)),
      );
    const onClose = vi.fn();
    const { result } = renderHook(() => useAutoSave(save));
    act(() => result.current.schedule());
    let first!: Promise<void>;
    let second!: Promise<void>;
    await act(async () => {
      first = result.current.requestClose(onClose);
      second = result.current.requestClose(onClose);
    });
    expect(save).toHaveBeenCalledOnce();
    await act(async () => finishSave(false));
    expect(feedback.confirm).toHaveBeenCalledOnce();
    let third!: Promise<void>;
    await act(async () => {
      third = result.current.requestClose(onClose);
    });
    expect(feedback.confirm).toHaveBeenCalledOnce();
    await act(async () => {
      const confirmation = feedback.confirm.mock.calls[0][0] as ModalFuncProps;
      confirmation.onOk?.();
      await Promise.all([first, second, third]);
    });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("waits for newer edits before completing a close request", async () => {
    let finishSave!: () => void;
    const save = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise<void>((resolve) => (finishSave = resolve)),
      )
      .mockResolvedValue(undefined);
    const onClose = vi.fn();
    const { result } = renderHook(() => useAutoSave(save));
    act(() => result.current.schedule());
    let closing!: Promise<void>;
    await act(async () => {
      closing = result.current.requestClose(onClose);
    });
    act(() => result.current.schedule());
    await act(async () => {
      finishSave();
      await closing;
    });
    expect(save).toHaveBeenCalledTimes(2);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("invalidates failed-save retry actions when changes are discarded", async () => {
    const save = vi.fn().mockRejectedValue(new Error("offline"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { result, unmount } = renderHook(() => useAutoSave(save));
    act(() => result.current.schedule());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    const toast = feedback.error.mock.calls[0][0];
    const retry = toast.content.props.children[2].props.onClick;
    act(() => result.current.discard());
    await act(async () => retry());
    unmount();
    await act(async () => {});
    expect(save).toHaveBeenCalledOnce();
    expect(feedback.destroy).toHaveBeenCalledWith(toast.key);
  });

  it("does not restore a discarded job when an in-flight save fails", async () => {
    let failSave!: (error: Error) => void;
    const save = vi
      .fn()
      .mockImplementation(
        () => new Promise<void>((_, reject) => (failSave = reject)),
      );
    const { result, unmount } = renderHook(() => useAutoSave(save));
    act(() => result.current.schedule());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    act(() => result.current.discard());
    await act(async () => failSave(new Error("offline")));
    await act(() => result.current.flush());
    expect(feedback.error).not.toHaveBeenCalled();
    unmount();
    expect(save).toHaveBeenCalledOnce();
  });
});
