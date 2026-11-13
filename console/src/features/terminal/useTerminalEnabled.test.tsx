import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { request } from "../../api/request";
import { AuthStatusProvider } from "../../contexts/AuthStatusContext";
import { useTerminalEnabled } from "./useTerminalEnabled";

vi.mock("../../api/request", () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function authWrapper(enabled: boolean) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <AuthStatusProvider value={{ enabled, has_users: true }}>
        {children}
      </AuthStatusProvider>
    );
  };
}

describe("terminal authentication capability", () => {
  it("does not request terminal status when authentication is disabled", () => {
    const { result } = renderHook(() => useTerminalEnabled(), {
      wrapper: authWrapper(false),
    });

    expect(result.current).toEqual({
      enabled: false,
      reason: "",
      confirmed: true,
    });
    expect(request).not.toHaveBeenCalled();
  });

  it.each([true, false])("honors backend enabled=%s", async (enabled) => {
    vi.mocked(request).mockResolvedValue({ enabled });
    const { result } = renderHook(() => useTerminalEnabled(), {
      wrapper: authWrapper(true),
    });
    expect(result.current.enabled).toBe(false);
    expect(result.current.confirmed).toBe(false);
    await waitFor(() => expect(request).toHaveBeenCalled());
    await waitFor(() => expect(result.current.enabled).toBe(enabled));
    expect(result.current.confirmed).toBe(true);
  });
  it("fails closed when capability loading fails", async () => {
    vi.mocked(request).mockRejectedValue(new Error("unavailable"));
    const { result } = renderHook(() => useTerminalEnabled(), {
      wrapper: authWrapper(true),
    });
    await waitFor(() => expect(result.current.reason).toBe("unavailable"));
    expect(result.current.enabled).toBe(false);
    expect(result.current.confirmed).toBe(false);
  });
  it("preserves the missing dependency reason", async () => {
    vi.mocked(request).mockResolvedValue({
      enabled: false,
      reason: "dependency_missing",
    });
    const { result } = renderHook(() => useTerminalEnabled(), {
      wrapper: authWrapper(true),
    });
    await waitFor(() =>
      expect(result.current.reason).toBe("dependency_missing"),
    );
    expect(result.current.enabled).toBe(false);
    expect(result.current.confirmed).toBe(true);
  });
  it("does not refresh a confirmed status on focus", async () => {
    vi.mocked(request).mockResolvedValue({ enabled: true });
    const { result } = renderHook(() => useTerminalEnabled(), {
      wrapper: authWrapper(true),
    });
    await waitFor(() => expect(result.current.enabled).toBe(true));

    act(() => window.dispatchEvent(new Event("focus")));

    expect(request).toHaveBeenCalledTimes(1);
    expect(result.current).toEqual({
      enabled: true,
      reason: "",
      confirmed: true,
    });
  });
  it("retries an unconfirmed status on focus", async () => {
    vi.mocked(request)
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce({ enabled: true });
    const { result } = renderHook(() => useTerminalEnabled(), {
      wrapper: authWrapper(true),
    });
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(result.current.confirmed).toBe(false);

    act(() => window.dispatchEvent(new Event("focus")));

    await waitFor(() => expect(result.current.enabled).toBe(true));
    expect(request).toHaveBeenCalledTimes(2);
  });
});
