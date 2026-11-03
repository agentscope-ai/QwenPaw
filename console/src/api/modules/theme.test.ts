import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { request } from "../request";
import { themeApi } from "./theme";

describe("themeApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("reads sparse theme values", async () => {
    vi.mocked(request).mockResolvedValue({ accent: "#0b57d0" });

    await expect(themeApi.get()).resolves.toEqual({ accent: "#0b57d0" });
    expect(request).toHaveBeenCalledWith("/config/theme");
  });

  it("updates the persisted theme", async () => {
    const theme = { accent: "#0b57d0", radius: "12px" };
    vi.mocked(request).mockResolvedValue(theme);

    await expect(themeApi.update(theme)).resolves.toEqual(theme);
    expect(request).toHaveBeenCalledWith("/config/theme", {
      method: "PUT",
      body: JSON.stringify(theme),
    });
  });

  it("resets the persisted theme", async () => {
    vi.mocked(request).mockResolvedValue(undefined);

    await expect(themeApi.reset()).resolves.toBeUndefined();
    expect(request).toHaveBeenCalledWith("/config/theme", {
      method: "DELETE",
    });
  });
});
