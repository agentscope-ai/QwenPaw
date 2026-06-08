import { vi } from "vitest";

export const invoke = vi.fn<(...args: unknown[]) => Promise<unknown>>(() =>
  Promise.resolve(undefined),
);
export const isTauri = vi.fn<() => boolean>(() => false);
export const save = vi.fn<() => Promise<string | null>>(() =>
  Promise.resolve(null),
);
