import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { App } from "antd";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { debugApi } from "@/api/modules/debug";
import { useDebugLogs } from "./useDebugLogs";

vi.mock("@/api/modules/debug", () => ({
  debugApi: { getBackendLogs: vi.fn() },
}));

const logs = {
  path: "qwenpaw.log",
  exists: true,
  lines: 200,
  updated_at: 1,
  size: 20,
  content: "INFO safe administrator log",
};
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <App>{children}</App>
);

beforeEach(() => {
  vi.mocked(debugApi.getBackendLogs).mockReset();
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "admin", platform_role: "admin" } as never,
  });
});

afterEach(() => cleanup());

it("does not request global logs for an ordinary member", async () => {
  useAuthStore.setState({
    user: { id: "member", platform_role: "member" } as never,
  });

  const { result } = renderHook(useDebugLogs, { wrapper });

  await waitFor(() => expect(result.current.initialLoading).toBe(false));
  expect(debugApi.getBackendLogs).not.toHaveBeenCalled();
  expect(result.current.backendLogs).toBeNull();
});

it("discards administrator logs that arrive after an identity switch", async () => {
  let finish!: (value: typeof logs) => void;
  vi.mocked(debugApi.getBackendLogs).mockImplementation(
    () => new Promise((resolve) => (finish = resolve)),
  );
  const { result } = renderHook(useDebugLogs, { wrapper });

  act(() => {
    useAuthStore.setState({
      user: { id: "member", platform_role: "member" } as never,
    });
  });
  await act(async () => finish(logs));

  expect(result.current.backendLogs).toBeNull();
  expect(result.current.filteredBackendLines).toEqual([]);
});
