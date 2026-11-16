import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  addToolRenderers: vi.fn(),
  adaptRegistryForV1: vi.fn(),
  registry: { alpha: {}, beta: {} },
}));

vi.mock("../../../plugins/hostExternals", () => ({
  pluginSystem: { addToolRenderers: h.addToolRenderers },
}));

vi.mock("./cards", () => ({ BUILTIN_CARD_REGISTRY: h.registry }));

vi.mock("./adapters/v1Adapter", () => ({
  adaptRegistryForV1: h.adaptRegistryForV1,
}));

// `registered` is module-level state, so every test needs a fresh module
// instance to exercise the first-call path again.
async function freshImport() {
  vi.resetModules();
  return import("./registerBuiltinCards");
}

beforeEach(() => {
  vi.clearAllMocks();
  h.adaptRegistryForV1.mockReturnValue({ alpha: "A", beta: "B" });
  vi.spyOn(console, "info").mockImplementation(() => {});
});

describe("registerBuiltinCards", () => {
  it("adapts the builtin registry and registers it under the builtin plugin id", async () => {
    const { registerBuiltinCards } = await freshImport();
    registerBuiltinCards();
    expect(h.adaptRegistryForV1).toHaveBeenCalledWith(h.registry);
    expect(h.addToolRenderers).toHaveBeenCalledWith(
      "builtin-tool-cards",
      { alpha: "A", beta: "B" },
      { isBuiltin: true },
    );
  });

  it("logs how many cards were registered and their names", async () => {
    const info = vi.mocked(console.info);
    const { registerBuiltinCards } = await freshImport();
    registerBuiltinCards();
    expect(info).toHaveBeenCalledTimes(1);
    const [template, names] = info.mock.calls[0];
    expect(String(template)).toContain("2 tool cards");
    expect(names).toBe("alpha, beta");
  });

  it("registers nothing on a second call within the same module instance", async () => {
    const { registerBuiltinCards } = await freshImport();
    registerBuiltinCards();
    registerBuiltinCards();
    registerBuiltinCards();
    expect(h.addToolRenderers).toHaveBeenCalledTimes(1);
    expect(h.adaptRegistryForV1).toHaveBeenCalledTimes(1);
  });

  it("does not even log on the guarded second call", async () => {
    const info = vi.mocked(console.info);
    const { registerBuiltinCards } = await freshImport();
    registerBuiltinCards();
    registerBuiltinCards();
    expect(info).toHaveBeenCalledTimes(1);
  });

  it("registers again for a fresh module instance, proving the guard is module state", async () => {
    const first = await freshImport();
    first.registerBuiltinCards();
    expect(h.addToolRenderers).toHaveBeenCalledTimes(1);

    h.adaptRegistryForV1.mockReturnValue({ gamma: "C" });
    const second = await freshImport();
    second.registerBuiltinCards();
    expect(h.addToolRenderers).toHaveBeenCalledTimes(2);
    expect(h.addToolRenderers).toHaveBeenLastCalledWith(
      "builtin-tool-cards",
      { gamma: "C" },
      { isBuiltin: true },
    );
  });

  it("handles an empty adapted registry without throwing", async () => {
    h.adaptRegistryForV1.mockReturnValue({});
    const { registerBuiltinCards } = await freshImport();
    expect(() => registerBuiltinCards()).not.toThrow();
    expect(h.addToolRenderers).toHaveBeenCalledWith(
      "builtin-tool-cards",
      {},
      { isBuiltin: true },
    );
  });

  it("marks the guard as set even if registering throws, so it is not retried", async () => {
    // The flag is flipped BEFORE addToolRenderers runs, so a throw leaves the
    // module permanently registered. Pinned as-is: whether that is desirable is
    // a product decision, not something a test should silently change.
    h.addToolRenderers.mockImplementationOnce(() => {
      throw new Error("plugin system down");
    });
    const { registerBuiltinCards } = await freshImport();
    expect(() => registerBuiltinCards()).toThrow("plugin system down");
    expect(() => registerBuiltinCards()).not.toThrow();
    expect(h.addToolRenderers).toHaveBeenCalledTimes(1);
  });
});
