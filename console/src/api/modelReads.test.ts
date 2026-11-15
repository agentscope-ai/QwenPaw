import { beforeEach, expect, it, vi } from "vitest";
const auth = vi.hoisted(() => ({ generation: 0, agent: "a" }));
vi.mock("./request", () => ({ request: vi.fn() }));
vi.mock("../stores/authStore", () => ({
  useAuthStore: { getState: () => ({ user: { id: "test-user" } }) },
}));
vi.mock("./authSession", () => ({
  getAccessSessionGeneration: () => auth.generation,
  subscribeAccessSessionGeneration: () => () => {},
}));
vi.mock("./authHeaders", () => ({
  buildAuthHeaders: () => ({ "X-Agent-Id": auth.agent }),
}));
vi.mock("./config", () => ({ getApiUrl: (path: string) => path }));
import { request } from "./request";
import { invalidateModelReads, readModelMetadata } from "./modelReads";

beforeEach(() => {
  invalidateModelReads();
  vi.mocked(request).mockReset();
  auth.generation = 0;
  auth.agent = "a";
});
it("coalesces simultaneous and adjacent reads, but expires the short cache", async () => {
  vi.useFakeTimers();
  try {
    vi.mocked(request).mockResolvedValue({ model: "m" });
    await Promise.all([
      readModelMetadata("/model"),
      readModelMetadata("/model"),
    ]);
    await readModelMetadata("/model");
    expect(request).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1001);
    await readModelMetadata("/model");
    expect(request).toHaveBeenCalledTimes(2);
  } finally {
    vi.useRealTimers();
  }
});
it("isolates Agent and authentication generations with explicit headers", async () => {
  vi.mocked(request).mockResolvedValue({});
  await readModelMetadata("/model");
  auth.agent = "b";
  await readModelMetadata("/model");
  auth.generation++;
  await readModelMetadata("/model");
  expect(request).toHaveBeenCalledTimes(3);
  expect(request).toHaveBeenLastCalledWith("/model", {
    headers: { "X-Agent-Id": "b" },
  });
});
it("rejects a late read after selection changes and does not replace a newer read", async () => {
  let done!: (value: unknown) => void;
  vi.mocked(request)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          done = resolve;
        }),
    )
    .mockResolvedValue({ model: "new" });
  const old = readModelMetadata("/model");
  const rejected = expect(old).rejects.toMatchObject({ name: "AbortError" });
  invalidateModelReads();
  expect(await readModelMetadata("/model")).toEqual({ model: "new" });
  done({ model: "old" });
  await rejected;
  expect(await readModelMetadata("/model")).toEqual({ model: "new" });
  expect(request).toHaveBeenCalledTimes(2);
});
it("does not cache failed or forbidden reads", async () => {
  vi.mocked(request)
    .mockRejectedValueOnce(new Error("forbidden"))
    .mockResolvedValue({});
  await expect(readModelMetadata("/model")).rejects.toThrow("forbidden");
  await readModelMetadata("/model");
  expect(request).toHaveBeenCalledTimes(2);
});
