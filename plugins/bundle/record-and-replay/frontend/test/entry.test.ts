import { describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
  chat: { rightHeader: { add: vi.fn() } },
  menu: { add: vi.fn() },
  route: { add: vi.fn() },
}));
vi.mock("../src/host", async () => ({
  host: { React: await import("react") },
  qwenpaw: sdk,
}));
vi.mock("../src/surface", () => ({ RecordingSurface: () => null }));

describe("plugin entry", () => {
  it("registers only its own controls, route and menu through the existing SDK", async () => {
    await import("../src/index");
    expect(sdk.chat.rightHeader.add).toHaveBeenCalledWith(
      "record-and-replay",
      expect.anything(),
      { id: "recording-controls", order: 60 },
    );
    expect(sdk.route.add).toHaveBeenCalledWith(
      "record-and-replay",
      expect.objectContaining({
        id: "record-and-replay.settings",
        path: "/plugin/record-and-replay",
      }),
    );
    expect(sdk.menu.add).toHaveBeenCalledWith(
      "record-and-replay",
      expect.objectContaining({
        id: "record-and-replay.settings",
        location: "primary.settings",
        route: "record-and-replay.settings",
      }),
    );
  });
});
