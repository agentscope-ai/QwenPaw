import { expect, it, vi } from "vitest";
import { InputMessageRecall } from "./inputMessageRecall";
const item = (n: number) => ({
  messageId: String(n),
  preview: "truncated",
  createdAt: "",
  anchor: "",
});
it("crosses page boundaries both ways and restores the draft after the newest input", async () => {
  const page = vi.fn(async (before?: string) =>
    before === "older"
      ? { items: [item(1), item(2)] }
      : { items: [item(3), item(4)], before: "older" },
  );
  const text = vi.fn(async (id: string) => `full ${id}\nsecond line`);
  const recall = new InputMessageRecall(page, text);
  for (const n of [4, 3, 2, 1])
    expect(await recall.move(true)).toBe(`full ${n}\nsecond line`);
  expect(await recall.move(true)).toBeUndefined();
  for (const n of [2, 3, 4])
    expect(await recall.move(false)).toBe(`full ${n}\nsecond line`);
  expect(await recall.move(false)).toBeNull();
  expect(page.mock.calls.map((call) => call[0])).toEqual([
    undefined,
    "older",
    undefined,
  ]);
  expect(text).toHaveBeenCalledTimes(4);
});
it("skips empty inputs and retries a failed full-text read", async () => {
  const text = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce("")
    .mockResolvedValueOnce("first");
  const recall = new InputMessageRecall(
    async () => ({ items: [item(1), item(2)] }),
    text,
  );
  await expect(recall.move(true)).rejects.toThrow("offline");
  expect(await recall.move(true)).toBe("first");
});

it("always reads original text and reuses its cache", async () => {
  const text = vi.fn(async (id: string) => `original ${id}\nwith spacing`);
  const recall = new InputMessageRecall(
    async () => ({ items: [item(1), item(2)] }),
    text,
  );
  expect(await recall.move(true)).toBe("original 2\nwith spacing");
  expect(await recall.move(true)).toBe("original 1\nwith spacing");
  expect(await recall.move(false)).toBe("original 2\nwith spacing");
  expect(text.mock.calls.map(([id]) => id)).toEqual(["2", "1"]);
});

it("evicts old full texts after twenty entries", async () => {
  const text = vi.fn(async (id: string) => id);
  const recall = new InputMessageRecall(
    async () => ({ items: Array.from({ length: 21 }, (_, i) => item(i + 1)) }),
    text,
  );
  for (let i = 21; i >= 1; i--) expect(await recall.move(true)).toBe(String(i));
  for (let i = 2; i <= 21; i++)
    expect(await recall.move(false)).toBe(String(i));
  expect(text).toHaveBeenCalledTimes(22);
  expect(text.mock.calls.filter(([id]) => id === "21")).toHaveLength(2);
});
