// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadPawApp } from "./usePluginLoader";
import { usePawAppRuntime } from "./usePawAppRuntime";

vi.mock("./usePluginLoader", () => ({
  loadPawApp: vi.fn(),
}));

describe("usePawAppRuntime", () => {
  beforeEach(() => {
    vi.mocked(loadPawApp).mockReset();
  });

  it("loads once across unrelated rerenders", async () => {
    vi.mocked(loadPawApp).mockResolvedValue();
    const { result, rerender } = renderHook(
      ({ appId, entryPage }) => usePawAppRuntime(appId, entryPage),
      {
        initialProps: { appId: "notes", entryPage: "/apps/notes" },
      },
    );

    await waitFor(() => expect(result.current.state).toBe("ready"));
    rerender({ appId: "notes", entryPage: "/apps/notes" });

    expect(loadPawApp).toHaveBeenCalledTimes(1);
    expect(loadPawApp).toHaveBeenCalledWith("notes", "/apps/notes");
  });

  it("retries after a failed load", async () => {
    vi.mocked(loadPawApp)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce();
    const { result } = renderHook(() =>
      usePawAppRuntime("notes", "/apps/notes"),
    );

    await waitFor(() => expect(result.current.state).toBe("failed"));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.state).toBe("ready"));

    expect(loadPawApp).toHaveBeenCalledTimes(2);
  });
});
