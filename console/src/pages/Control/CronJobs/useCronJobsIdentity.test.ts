// 账户、Agent 与查询范围切换均不得继承旧的任务列表或回滚结果。
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import api from "../../../api";
import { useAuthStore } from "../../../stores/authStore";
import { useAgentStore } from "../../../stores/agentStore";
import { useCronJobs } from "./useCronJobs";

vi.mock("../../../api", () => ({
  default: {
    listCronJobs: vi.fn(),
    createCronJob: vi.fn(),
    replaceCronJob: vi.fn(),
    deleteCronJob: vi.fn(),
    triggerCronJob: vi.fn(),
    pauseCronJob: vi.fn(),
    resumeCronJob: vi.fn(),
    getCronJobAuthorization: vi.fn(),
    authorizeCronJob: vi.fn(),
  },
}));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: vi.fn(), success: vi.fn() } }),
}));
vi.mock("react-i18next", async (original) => ({
  ...(await original<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (value: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const ownJob = { id: "own-job", name: "private A job", enabled: true };
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "account-a", platform_role: "member" } as never,
  });
  useAgentStore.setState({ selectedAgent: "default" });
});
afterEach(cleanup);

it("does not keep account A's jobs when B uses the same Agent", async () => {
  vi.mocked(api.listCronJobs).mockResolvedValue([ownJob] as never);
  const { result, rerender } = renderHook(() => useCronJobs());
  await waitFor(() =>
    expect(result.current.jobs[0]?.name).toBe("private A job"),
  );
  vi.mocked(api.listCronJobs).mockResolvedValue([]);
  act(() => {
    useAuthStore.setState({
      user: { id: "account-b", platform_role: "member" } as never,
    });
  });
  rerender();
  expect(result.current.jobs).toEqual([]);
});

it("does not restore A's deleted job from a failed old-account request", async () => {
  const pending = deferred<never>();
  vi.mocked(api.listCronJobs).mockResolvedValue([ownJob] as never);
  vi.mocked(api.deleteCronJob).mockReturnValue(pending.promise);
  const { result, rerender } = renderHook(() => useCronJobs());
  await waitFor(() =>
    expect(result.current.jobs[0]?.name).toBe("private A job"),
  );
  let deletion!: Promise<unknown>;
  act(() => {
    deletion = result.current.deleteJob(ownJob.id);
  });
  expect(result.current.jobs).toEqual([]);
  vi.mocked(api.listCronJobs).mockResolvedValue([]);
  act(() => {
    useAuthStore.setState({
      user: { id: "account-b", platform_role: "member" } as never,
    });
  });
  rerender();
  await act(async () => {
    pending.reject(new DOMException("Identity changed", "AbortError"));
    await deletion;
  });
  expect(result.current.jobs).toEqual([]);
});

it("ignores a late create result after the account switches", async () => {
  const pending = deferred<never>();
  vi.mocked(api.listCronJobs).mockResolvedValue([]);
  vi.mocked(api.createCronJob).mockReturnValue(pending.promise);
  const { result } = renderHook(() => useCronJobs());
  await waitFor(() => expect(result.current.loading).toBe(false));
  let creation!: Promise<unknown>;
  act(() => {
    creation = result.current.createJob(ownJob as never);
  });
  act(() => {
    useAuthStore.setState({
      user: { id: "account-b", platform_role: "member" } as never,
    });
  });
  await act(async () => {
    pending.resolve(ownJob as never);
    await creation;
  });
  expect(result.current.jobs).toEqual([]);
});

it("does not continue an old account's two-step authorization", async () => {
  const pending = deferred<never>();
  vi.mocked(api.listCronJobs).mockResolvedValue([]);
  vi.mocked(api.getCronJobAuthorization).mockReturnValue(pending.promise);
  const { result } = renderHook(() => useCronJobs());
  await waitFor(() => expect(result.current.loading).toBe(false));
  let authorization!: Promise<unknown>;
  act(() => {
    authorization = result.current.authorizeJob("own-job");
  });
  act(() => {
    useAuthStore.setState({
      user: { id: "account-b", platform_role: "member" } as never,
    });
  });
  await act(async () => {
    pending.resolve({
      config_version: 1,
      authorization_digest: "fixture",
    } as never);
    await authorization;
  });
  expect(api.authorizeCronJob).not.toHaveBeenCalled();
});

it("ignores an earlier Agent's list response after a switch", async () => {
  const pending = deferred<never>();
  vi.mocked(api.listCronJobs)
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValue([]);
  const { result } = renderHook(() => useCronJobs());
  act(() => {
    useAgentStore.setState({ selectedAgent: "another-agent" });
  });
  await act(async () => {
    pending.resolve([ownJob] as never);
  });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.jobs).toEqual([]);
});

it("invalidates callbacks captured under an earlier task query scope", async () => {
  vi.mocked(api.listCronJobs).mockResolvedValue([]);
  const { result, rerender } = renderHook(
    ({ scope }: { scope: "mine" | "agent" }) => useCronJobs(scope),
    { initialProps: { scope: "mine" } },
  );
  await waitFor(() => expect(result.current.loading).toBe(false));
  const oldTrigger = result.current.executeNow;
  rerender({ scope: "agent" });
  await act(async () => {
    expect(await oldTrigger("old-job")).toBe(false);
  });
  expect(api.triggerCronJob).not.toHaveBeenCalled();
});

it("keeps jobs through token renewal but resets them when Agent role changes", async () => {
  useAgentStore.setState({
    agents: [{ id: "default", enabled: true, access_role: "owner" }] as never,
  });
  vi.mocked(api.listCronJobs).mockResolvedValue([ownJob] as never);
  const { result } = renderHook(() => useCronJobs());
  await waitFor(() => expect(result.current.jobs).toHaveLength(1));
  const count = vi.mocked(api.listCronJobs).mock.calls.length;
  act(() => {
    useAuthStore.setState({ accessToken: "renewed-token" });
  });
  expect(result.current.jobs[0]?.name).toBe("private A job");
  expect(api.listCronJobs).toHaveBeenCalledTimes(count);
  vi.mocked(api.listCronJobs).mockResolvedValue([]);
  act(() => {
    useAgentStore.setState({
      agents: [{ id: "default", enabled: true, access_role: "user" }] as never,
    });
  });
  expect(result.current.jobs).toEqual([]);
});
