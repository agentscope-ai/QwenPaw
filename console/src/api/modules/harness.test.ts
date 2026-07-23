import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { request } from "../request";
import { harnessApi } from "./harness";

describe("harnessApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads the provider catalog with a startup timeout", async () => {
    await harnessApi.list();

    expect(request).toHaveBeenCalledWith("/harnesses", {
      timeout: 60_000,
    });
  });

  it("starts Codex OAuth without exposing credentials", async () => {
    await harnessApi.login("codex");

    expect(request).toHaveBeenCalledWith("/harnesses/codex/login", {
      method: "POST",
      body: JSON.stringify({ device_code: false }),
      timeout: 60_000,
    });
  });

  it("logs Codex out through the harness API", async () => {
    await harnessApi.logout("codex");

    expect(request).toHaveBeenCalledWith("/harnesses/codex/logout", {
      method: "POST",
    });
  });

  it("loads models through a provider-neutral route", async () => {
    await harnessApi.listModels("codex");

    expect(request).toHaveBeenCalledWith("/harnesses/codex/models", {
      timeout: 60_000,
    });
  });
});
