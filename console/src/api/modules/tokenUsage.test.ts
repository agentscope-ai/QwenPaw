import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { tokenUsageApi } from "./tokenUsage";
import { request } from "../request";

describe("tokenUsageApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getTokenUsage builds query with start_date + end_date only", async () => {
    const summary = { total_tokens: 100 } as any;
    vi.mocked(request).mockResolvedValue(summary);
    const result = await tokenUsageApi.getTokenUsage({
      start_date: "2026-01-01",
      end_date: "2026-01-31",
    });
    expect(request).toHaveBeenCalledWith(
      "/token-usage?start_date=2026-01-01&end_date=2026-01-31",
    );
    expect(result).toEqual(summary);
  });

  it("getTokenUsageDetails includes model + provider when provided", async () => {
    const records = [{ id: "r1" }] as any;
    vi.mocked(request).mockResolvedValue(records);
    const result = await tokenUsageApi.getTokenUsageDetails({
      start_date: "2026-01-01",
      end_date: "2026-01-31",
      model: "gpt-4",
      provider: "openai",
    });
    expect(request).toHaveBeenCalledWith(
      "/token-usage/details?start_date=2026-01-01&end_date=2026-01-31&model=gpt-4&provider=openai",
    );
    expect(result).toEqual(records);
  });

  it("getTokenUsageDetails omits model/provider query when not provided", async () => {
    const records = [] as any;
    vi.mocked(request).mockResolvedValue(records);
    await tokenUsageApi.getTokenUsageDetails({
      start_date: "2026-02-01",
      end_date: "2026-02-28",
    });
    expect(request).toHaveBeenCalledWith(
      "/token-usage/details?start_date=2026-02-01&end_date=2026-02-28",
    );
  });
});
