import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";

// Ant Design's App.useApp reads from context. We mock the module so we can
// assert that useAppMessage forwards message/modal/notification unchanged.
vi.mock("antd", () => {
  const App = {
    useApp: vi.fn(),
  };
  return { App };
});

import { App } from "antd";
import { useAppMessage } from "./useAppMessage";

describe("useAppMessage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns the message instance from App.useApp", () => {
    const message = { success: vi.fn(), error: vi.fn() };
    const modal = { confirm: vi.fn() };
    const notification = { open: vi.fn() };
    (App.useApp as ReturnType<typeof vi.fn>).mockReturnValue({
      message,
      modal,
      notification,
    });

    const { result } = renderHook(() => useAppMessage());
    expect(result.current.message).toBe(message);
  });

  it("returns the modal instance from App.useApp", () => {
    const modal = { confirm: vi.fn() };
    (App.useApp as ReturnType<typeof vi.fn>).mockReturnValue({
      message: {},
      modal,
      notification: {},
    });

    const { result } = renderHook(() => useAppMessage());
    expect(result.current.modal).toBe(modal);
  });

  it("returns the notification instance from App.useApp", () => {
    const notification = { open: vi.fn() };
    (App.useApp as ReturnType<typeof vi.fn>).mockReturnValue({
      message: {},
      modal: {},
      notification,
    });

    const { result } = renderHook(() => useAppMessage());
    expect(result.current.notification).toBe(notification);
  });

  it("calls App.useApp exactly once per render", () => {
    (App.useApp as ReturnType<typeof vi.fn>).mockReturnValue({
      message: {},
      modal: {},
      notification: {},
    });

    renderHook(() => useAppMessage());
    expect(App.useApp).toHaveBeenCalledTimes(1);
  });

  it("returns fresh instances on re-render", () => {
    const first = { message: { a: 1 }, modal: {}, notification: {} };
    const second = { message: { b: 2 }, modal: {}, notification: {} };
    (App.useApp as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(first)
      .mockReturnValueOnce(second);

    const { result, rerender } = renderHook(() => useAppMessage());
    expect(result.current.message).toBe(first.message);

    rerender();
    expect(result.current.message).toBe(second.message);
  });
});
