import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { request } from "../../api/request";
import { useTerminalEnabled } from "./useTerminalEnabled";

vi.mock("../../api/request", () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
describe("terminal authentication capability", () => {
  it.each([true, false])("honors backend enabled=%s", async (enabled) => {
    vi.mocked(request).mockResolvedValue({ enabled });
    const { result } = renderHook(() => useTerminalEnabled("agent"));
    expect(result.current.enabled).toBe(false);
    expect(result.current.confirmed).toBe(false);
    await waitFor(() => expect(request).toHaveBeenCalled());
    await waitFor(() => expect(result.current.enabled).toBe(enabled));
    expect(result.current.confirmed).toBe(true);
  });
  it("fails closed when capability loading fails", async () => {
    vi.mocked(request).mockRejectedValue(new Error("unavailable"));
    const { result } = renderHook(() => useTerminalEnabled("agent"));
    await waitFor(() => expect(result.current.reason).toBe("unavailable"));
    expect(result.current.enabled).toBe(false);
    expect(result.current.confirmed).toBe(false);
  });
  it("preserves the missing dependency reason", async () => {
    vi.mocked(request).mockResolvedValue({
      enabled: false,
      reason: "dependency_missing",
    });
    const { result } = renderHook(() => useTerminalEnabled("agent"));
    await waitFor(() =>
      expect(result.current.reason).toBe("dependency_missing"),
    );
    expect(result.current.enabled).toBe(false);
    expect(result.current.confirmed).toBe(true);
  });
  it("keeps a confirmed status when a focus refresh fails", async () => {
    vi.mocked(request)
      .mockResolvedValueOnce({ enabled: true })
      .mockRejectedValueOnce(new Error("unavailable"));
    const { result } = renderHook(() => useTerminalEnabled("agent"));
    await waitFor(() => expect(result.current.enabled).toBe(true));

    window.dispatchEvent(new Event("focus"));

    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    expect(result.current).toEqual({
      enabled: true,
      reason: "",
      confirmed: true,
    });
  });
  it("restores the cached status when switching back to an agent", async () => {
    vi.mocked(request)
      .mockResolvedValueOnce({ enabled: true })
      .mockImplementationOnce(() => new Promise(() => undefined));
    const { result, rerender } = renderHook(
      ({ agentId }) => useTerminalEnabled(agentId),
      { initialProps: { agentId: "agent-a" } },
    );
    await waitFor(() => expect(result.current.enabled).toBe(true));

    rerender({ agentId: "agent-b" });
    expect(result.current.confirmed).toBe(false);
    rerender({ agentId: "agent-a" });

    expect(result.current).toEqual({
      enabled: true,
      reason: "",
      confirmed: true,
    });
  });
});
