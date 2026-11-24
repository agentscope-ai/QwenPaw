import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const Button = () => null;
const ExtraIcon = () => null;

beforeEach(() => {
  vi.resetModules();
  vi.doMock("antd", () => ({ Button }));
  vi.doMock("@ant-design/icons", () => ({ ExtraIcon }));
});

afterEach(() => {
  vi.doUnmock("antd");
  vi.doUnmock("@ant-design/icons");
});

describe("plugin UI dependencies", () => {
  it("does not evaluate UI namespaces until preparation is requested", async () => {
    const factory = vi.fn(() => ({ Button }));
    vi.doMock("antd", factory);
    const { loadHostUiDependencies, getHostUiDependencies } = await import(
      "./hostUiDependencies"
    );
    expect(factory).not.toHaveBeenCalled();
    expect(getHostUiDependencies).toThrow("must be loaded");
    await loadHostUiDependencies();
    expect(factory).toHaveBeenCalledTimes(1);
    expect(getHostUiDependencies().antd.Button).toBe(Button);
  });

  it("deduplicates concurrent loads and retains complete namespace identity", async () => {
    const { loadHostUiDependencies, getHostUiDependencies } = await import(
      "./hostUiDependencies"
    );
    const first = loadHostUiDependencies();
    expect(loadHostUiDependencies()).toBe(first);
    await first;
    expect(loadHostUiDependencies()).toBe(first);
    expect(getHostUiDependencies().antd).toBe(await import("antd"));
    expect(getHostUiDependencies().antdIcons).toBe(
      await import("@ant-design/icons"),
    );
  });

  it("allows a failed namespace import to be retried", async () => {
    vi.doMock("antd", () => {
      throw new Error("UI import failed");
    });
    const { loadHostUiDependencies, getHostUiDependencies } = await import(
      "./hostUiDependencies"
    );
    const first = loadHostUiDependencies();
    await expect(first).rejects.toThrow();
    expect(getHostUiDependencies).toThrow("must be loaded");
    vi.doMock("antd", () => ({ Button }));
    const retry = loadHostUiDependencies();
    expect(retry).not.toBe(first);
    await retry;
    expect(getHostUiDependencies().antd.Button).toBe(Button);
  });

  it("keeps host getters synchronous and stable after preparation", async () => {
    const { installHostExternals } = await import("./hostExternals");
    const { loadHostUiDependencies } = await import("./hostUiDependencies");
    installHostExternals();
    const host = window.QwenPaw.host;
    await loadHostUiDependencies();
    expect(host.antd.Button).toBe(Button);
    expect(host.antdIcons).toHaveProperty("ExtraIcon", ExtraIcon);
    installHostExternals();
    expect(window.QwenPaw.host).toBe(host);
  });
});
