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
    expect(result.current).toBe(false);
    await waitFor(() => expect(request).toHaveBeenCalled());
    await waitFor(() => expect(result.current).toBe(enabled));
  });
  it("fails closed when capability loading fails", async () => {
    vi.mocked(request).mockRejectedValue(new Error("unavailable"));
    const { result } = renderHook(() => useTerminalEnabled("agent"));
    await waitFor(() => expect(result.current).toBe(false));
  });
});
