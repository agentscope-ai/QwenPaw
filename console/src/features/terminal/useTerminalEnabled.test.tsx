import { renderHook, waitFor, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { request } from "../../api/request";
import { useTerminalEnabled } from "./useTerminalEnabled";

vi.mock("../../api/request", () => ({ request: vi.fn() }));
afterEach(cleanup);
describe("terminal authentication capability", () => {
  it.each([true, false])("honors backend enabled=%s", async (enabled) => {
    vi.mocked(request).mockResolvedValue({ enabled });
    const { result } = renderHook(() => useTerminalEnabled("agent"));
    expect(result.current.enabled).toBe(false);
    await waitFor(() => expect(request).toHaveBeenCalled());
    await waitFor(() => expect(result.current.enabled).toBe(enabled));
  });
  it("fails closed when capability loading fails", async () => {
    vi.mocked(request).mockRejectedValue(new Error("unavailable"));
    const { result } = renderHook(() => useTerminalEnabled("agent"));
    await waitFor(() => expect(result.current.reason).toBe("unavailable"));
    expect(result.current.enabled).toBe(false);
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
  });
});
