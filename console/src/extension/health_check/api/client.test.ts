import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { securityApi } from "@/api/modules/security";

vi.mock("@/api/request", () => ({
  request: vi.fn(),
}));

vi.mock("@/api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));

import { request } from "@/api/request";

describe("securityApi health check", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("runIntegrityHealthCheckScan posts read-only scan by default", async () => {
    await securityApi.runIntegrityHealthCheckScan();
    expect(request).toHaveBeenCalledWith(
      "/config/security/integrity-protection/health-check/scan",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ deep: false }),
      }),
    );
  });

  it("runIntegrityHealthCheckScan posts deep=true for connectivity scan", async () => {
    await securityApi.runIntegrityHealthCheckScan(true);
    expect(request).toHaveBeenCalledWith(
      "/config/security/integrity-protection/health-check/scan",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ deep: true }),
      }),
    );
  });

  it("runIntegrityHealthCheckFix posts fix_id", async () => {
    await securityApi.runIntegrityHealthCheckFix("ensure-working-dir");
    expect(request).toHaveBeenCalledWith(
      "/config/security/integrity-protection/health-check/fix",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          fix_id: "ensure-working-dir",
          selected_repair: "repair_ensure-working-dir",
        }),
      }),
    );
  });
});
