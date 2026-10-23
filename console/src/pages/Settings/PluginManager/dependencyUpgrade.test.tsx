import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { createInstance, type TFunction } from "i18next";
import { renderToStaticMarkup } from "react-dom/server";
import en from "../../../locales/en.json";
import zh from "../../../locales/zh.json";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  apply: vi.fn(),
  cancel: vi.fn(),
  confirm: vi.fn(),
  info: vi.fn(),
  update: vi.fn(),
  destroy: vi.fn(),
  server: "http://server-a.test/api",
  agent: "workspace-a",
}));

vi.mock("../../../api/modules/plugin", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../api/modules/plugin")>()),
  fetchDependencyUpgrade: mocks.fetch,
  applyDependencyUpgrade: mocks.apply,
  cancelDependencyUpgrade: mocks.cancel,
}));
vi.mock("../../../api/config", () => ({
  getApiUrl: (path: string) => mocks.server + path,
}));
vi.mock("../../../api/authHeaders", () => ({
  buildAuthHeaders: () => ({ "X-Agent-Id": mocks.agent }),
}));
vi.mock("antd", () => ({
  Modal: { confirm: mocks.confirm, info: mocks.info },
}));

import { PluginApiError } from "../../../api/modules/plugin";
import {
  runPluginInstall,
  resumePendingPluginInstalls,
  getPendingUpgradeStorageKey,
} from "./dependencyUpgrade";

const t = ((key: string) => key) as TFunction;
const operation = {
  id: "reviewed-op",
  plugin_id: "matrix",
  status: "needs_confirmation" as const,
  changes: [
    {
      name: "markdown-it-py",
      current_version: "2.2.0",
      target_version: "3.0.0",
    },
  ],
  affected_instances: [
    {
      plugin_id: "consumer",
      instance_id: "running-1",
      generation: 7,
      origin: "runtime",
      active: true,
    },
  ],
  requires_restart: false,
  message: "Replace markdown-it-py only after confirmation",
  error: null,
  retryable: true,
};
const result = {
  id: "matrix",
  name: "Matrix",
  version: "0.1",
  description: "",
  loaded: true,
  message: "Installed",
};
const needsUpgrade = () =>
  Promise.reject(
    new PluginApiError("Review", 409, {
      code: "DEPENDENCY_UPGRADE_REQUIRED",
      operation,
    }),
  );
const flush = async () => {
  for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
};
const confirmedIds = () =>
  JSON.parse(localStorage.getItem(getPendingUpgradeStorageKey()) || "[]");

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  mocks.server = "http://server-a.test/api";
  mocks.agent = "workspace-a";
  for (const method of [
    mocks.fetch,
    mocks.apply,
    mocks.cancel,
    mocks.confirm,
    mocks.info,
    mocks.update,
    mocks.destroy,
  ])
    method.mockReset();
  mocks.confirm.mockReturnValue({
    update: mocks.update,
    destroy: mocks.destroy,
  });
  mocks.info.mockReturnValue({ update: mocks.update, destroy: mocks.destroy });
  mocks.cancel.mockResolvedValue({ ...operation, status: "cancelled" });
});
afterEach(() => vi.useRealTimers());

describe("shared dependency upgrade install flow", () => {
  it("leaves ordinary successful installs intact", async () => {
    await expect(runPluginInstall(async () => result, t)).resolves.toEqual(
      result,
    );
    expect(mocks.confirm).not.toHaveBeenCalled();
    expect(mocks.apply).not.toHaveBeenCalled();
    expect(confirmedIds()).toEqual([]);
  });

  it("requires explicit confirmation and cancellation has no success result", async () => {
    const installing = runPluginInstall(needsUpgrade, t);
    await flush();
    expect(mocks.confirm).toHaveBeenCalledOnce();
    expect(mocks.apply).not.toHaveBeenCalled();
    expect(confirmedIds()).toEqual([]);
    await mocks.confirm.mock.calls[0][0].onCancel();
    await expect(installing).resolves.toBeNull();
    expect(mocks.cancel).toHaveBeenCalledWith("reviewed-op");
    expect(mocks.apply).not.toHaveBeenCalled();
    expect(confirmedIds()).toEqual([]);
  });

  it("persists only a confirmed operation ID then follows server progress to install completion", async () => {
    mocks.apply.mockImplementation(async () => {
      expect(confirmedIds()).toEqual(["reviewed-op"]);
      return { ...operation, status: "applying" };
    });
    mocks.fetch
      .mockResolvedValueOnce({ ...operation, status: "applying" })
      .mockResolvedValue({ ...operation, status: "succeeded", result });
    const installing = runPluginInstall(needsUpgrade, t);
    await flush();
    void mocks.confirm.mock.calls[0][0].onOk();
    await flush();
    await vi.advanceTimersByTimeAsync(10000);
    await expect(installing).resolves.toEqual(result);
    expect(mocks.apply).toHaveBeenCalledOnce();
    expect(mocks.apply).toHaveBeenCalledWith("reviewed-op");
    expect(mocks.info).toHaveBeenCalled();
    expect(mocks.fetch).toHaveBeenCalledWith("reviewed-op");
    expect(confirmedIds()).toEqual([]);
    expect(mocks.cancel).not.toHaveBeenCalled();
  });

  it("resumes an already applying operation by reading status without applying twice", async () => {
    localStorage.setItem(
      getPendingUpgradeStorageKey(),
      JSON.stringify(["reviewed-op"]),
    );
    mocks.fetch
      .mockResolvedValueOnce({
        ...operation,
        status: "waiting_restart",
        requires_restart: true,
        instructions: ["Restart the backend to continue"],
      })
      .mockResolvedValue({ ...operation, status: "succeeded", result });
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const cleanup = resumePendingPluginInstalls(t, onSuccess, onError);
    await flush();
    await vi.advanceTimersByTimeAsync(10000);
    expect(onSuccess).toHaveBeenCalledWith(result);
    expect(onError).not.toHaveBeenCalled();
    expect(mocks.apply).not.toHaveBeenCalled();
    expect(mocks.info).toHaveBeenCalled();
    expect(confirmedIds()).toEqual([]);
    cleanup();
  });

  it("does not replay confirmed IDs against another server or workspace", async () => {
    const originalKey = getPendingUpgradeStorageKey();
    localStorage.setItem(originalKey, JSON.stringify(["reviewed-op"]));
    mocks.server = "http://server-b.test/api";
    let cleanup = resumePendingPluginInstalls(t, vi.fn(), vi.fn());
    await flush();
    expect(mocks.fetch).not.toHaveBeenCalled();
    cleanup();
    mocks.server = "http://server-a.test/api";
    mocks.agent = "workspace-b";
    cleanup = resumePendingPluginInstalls(t, vi.fn(), vi.fn());
    await flush();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(JSON.parse(localStorage.getItem(originalKey)!)).toEqual([
      "reviewed-op",
    ]);
    cleanup();
  });

  it("drops permanently missing operations and keeps failed network recovery available", async () => {
    localStorage.setItem(
      getPendingUpgradeStorageKey(),
      JSON.stringify(["gone", "offline"]),
    );
    mocks.fetch.mockImplementation(async (id: string) => {
      if (id === "gone") throw new PluginApiError("Missing", 404);
      throw new TypeError("Failed to fetch");
    });
    const onError = vi.fn();
    const cleanup = resumePendingPluginInstalls(t, vi.fn(), onError);
    await flush();
    await vi.advanceTimersByTimeAsync(120000);
    expect(confirmedIds()).toEqual(["offline"]);
    expect(onError).toHaveBeenCalled();
    expect(mocks.fetch.mock.calls.length).toBeLessThanOrEqual(8);
    expect(mocks.apply).not.toHaveBeenCalled();
    cleanup();
  });
});

it("foreground tracking owns completion so recovery cannot notify a second success", async () => {
  mocks.apply.mockResolvedValue({ ...operation, status: "applying" });
  mocks.fetch.mockResolvedValue({ ...operation, status: "succeeded", result });
  const installing = runPluginInstall(needsUpgrade, t);
  await flush();
  void mocks.confirm.mock.calls[0][0].onOk();
  await flush();
  expect(confirmedIds()).toEqual(["reviewed-op"]);
  const recoveredSuccess = vi.fn();
  const cleanup = resumePendingPluginInstalls(t, recoveredSuccess, vi.fn());
  await vi.advanceTimersByTimeAsync(10000);
  await expect(installing).resolves.toEqual(result);
  expect(mocks.apply).toHaveBeenCalledOnce();
  expect(recoveredSuccess).not.toHaveBeenCalled();
  cleanup();
});

it("cancellation racing another tab's apply follows the committed server operation", async () => {
  mocks.cancel.mockRejectedValue(
    new PluginApiError("Operation already applying", 409),
  );
  mocks.fetch
    .mockResolvedValueOnce({ ...operation, status: "applying" })
    .mockResolvedValue({ ...operation, status: "succeeded", result });
  const installing = runPluginInstall(needsUpgrade, t);
  await flush();
  void mocks.confirm.mock.calls[0][0].onCancel();
  await flush();
  expect(mocks.fetch).toHaveBeenCalledWith("reviewed-op");
  expect(confirmedIds()).toEqual(["reviewed-op"]);
  await vi.advanceTimersByTimeAsync(10000);
  await expect(installing).resolves.toEqual(result);
  expect(mocks.apply).not.toHaveBeenCalled();
  expect(confirmedIds()).toEqual([]);
});

it.each([
  ["en", en, /dependency/i, /restart/i],
  ["zh", zh, /共享依赖/, /重启/],
] as const)(
  "renders %s dependency impact and restart guidance before confirmation",
  async (language, resources, title, restart) => {
    const locale = createInstance();
    await locale.init({
      lng: language,
      resources: { [language]: { translation: resources } },
    });
    const installing = runPluginInstall(
      () =>
        Promise.reject(
          new PluginApiError("Review", 409, {
            code: "DEPENDENCY_UPGRADE_REQUIRED",
            operation: { ...operation, requires_restart: true },
          }),
        ),
      locale.t,
    );
    await flush();
    const dialog = mocks.confirm.mock.calls[0][0];
    expect(dialog.title).toMatch(title);
    const content = renderToStaticMarkup(dialog.content);
    expect(content).toContain("markdown-it-py");
    expect(content).toContain("2.2.0");
    expect(content).toContain("3.0.0");
    expect(content).toContain("consumer");
    expect(content).toContain("running-1");
    expect(content).toMatch(restart);
    expect(content).not.toContain("pluginManager.dependencyUpgrade");
    await dialog.onCancel();
    await expect(installing).resolves.toBeNull();
  },
);

it.each([401, 403])(
  "retains a confirmed operation through HTTP %s and resumes after authentication",
  async (status) => {
    localStorage.setItem(
      getPendingUpgradeStorageKey(),
      JSON.stringify(["reviewed-op"]),
    );
    mocks.fetch
      .mockRejectedValueOnce(new PluginApiError("Sign in again", status))
      .mockResolvedValue({ ...operation, status: "succeeded", result });
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const cleanup = resumePendingPluginInstalls(t, onSuccess, onError);
    await flush();
    expect(onError).toHaveBeenCalledOnce();
    expect(confirmedIds()).toEqual(["reviewed-op"]);
    expect(mocks.apply).not.toHaveBeenCalled();
    window.dispatchEvent(new Event("focus"));
    await flush();
    expect(onSuccess).toHaveBeenCalledWith(result);
    expect(confirmedIds()).toEqual([]);
    cleanup();
  },
);

it("a remounted recovery view adopts completion from a detached foreground install", async () => {
  const oldSuccess = vi.fn();
  const oldCleanup = resumePendingPluginInstalls(t, oldSuccess, vi.fn());
  mocks.apply.mockResolvedValue({ ...operation, status: "applying" });
  mocks.fetch.mockResolvedValue({ ...operation, status: "succeeded", result });
  const installing = runPluginInstall(needsUpgrade, t);
  await flush();
  void mocks.confirm.mock.calls[0][0].onOk();
  await flush();
  oldCleanup();
  const currentSuccess = vi.fn();
  const cleanup = resumePendingPluginInstalls(t, currentSuccess, vi.fn());
  await vi.advanceTimersByTimeAsync(10000);
  await expect(installing).resolves.toBeNull();
  expect(currentSuccess).toHaveBeenCalledExactlyOnceWith(result);
  expect(oldSuccess).not.toHaveBeenCalled();
  expect(mocks.apply).toHaveBeenCalledOnce();
  cleanup();
});

it.each([
  ["network disconnect", new TypeError("Connection lost")],
  ["service outage", new PluginApiError("Service unavailable", 503)],
])(
  "reconciles uncertain DELETE %s against the server before dropping tracking",
  async (_, failure) => {
    mocks.cancel.mockRejectedValue(failure);
    mocks.fetch
      .mockResolvedValueOnce({ ...operation, status: "applying" })
      .mockResolvedValue({ ...operation, status: "succeeded", result });
    const installing = runPluginInstall(needsUpgrade, t);
    await flush();
    void mocks.confirm.mock.calls[0][0].onCancel();
    await flush();
    expect(mocks.fetch).toHaveBeenCalledWith("reviewed-op");
    expect(confirmedIds()).toEqual(["reviewed-op"]);
    await vi.advanceTimersByTimeAsync(10000);
    await expect(installing).resolves.toEqual(result);
    expect(mocks.apply).not.toHaveBeenCalled();
  },
);
