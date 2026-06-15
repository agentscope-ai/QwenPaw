import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { securityApi } from "./security";

vi.mock("@/api/request", () => ({
  request: vi.fn(),
}));

vi.mock("@/api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));

import { request } from "@/api/request";

describe("securityApi persona protection", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getFileBaselineProtectionSettings calls settings endpoint", async () => {
    await securityApi.getFileBaselineProtectionSettings();
    expect(request).toHaveBeenCalledWith(
      "/config/security/file-baseline/settings",
    );
  });

  it("updateFileBaselineProtectionSettings sends PUT with enabled flag", async () => {
    await securityApi.updateFileBaselineProtectionSettings({ enabled: true });
    expect(request).toHaveBeenCalledWith(
      "/config/security/file-baseline/settings",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ enabled: true }),
      }),
    );
  });

  it("updateFileBaselineProtectionSettings includes confirmation phrase when re-enabling", async () => {
    await securityApi.updateFileBaselineProtectionSettings({
      enabled: true,
      confirmation_phrase: "Confirm re-establish file baseline",
    });
    expect(request).toHaveBeenCalledWith(
      "/config/security/file-baseline/settings",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          enabled: true,
          confirmation_phrase: "Confirm re-establish file baseline",
        }),
      }),
    );
  });

  it("getFileBaselineProtectionAlerts calls alerts endpoint", async () => {
    await securityApi.getFileBaselineProtectionAlerts();
    expect(request).toHaveBeenCalledWith(
      "/config/security/file-baseline/alerts",
    );
  });

  it("restoreFileBaselineProtectionAlert posts alert id and confirmation phrase", async () => {
    await securityApi.restoreFileBaselineProtectionAlert(
      "alert-123",
      "Confirm file baseline restore",
    );
    expect(request).toHaveBeenCalledWith(
      "/config/security/file-baseline/restore",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          alert_id: "alert-123",
          confirmation_phrase: "Confirm file baseline restore",
        }),
      }),
    );
  });

  it("acceptFileBaselineProtectionAlert posts alert id and confirmation phrase", async () => {
    await securityApi.acceptFileBaselineProtectionAlert(
      "alert-456",
      "Confirm file baseline accept",
    );
    expect(request).toHaveBeenCalledWith(
      "/config/security/file-baseline/accept",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          alert_id: "alert-456",
          confirmation_phrase: "Confirm file baseline accept",
        }),
      }),
    );
  });

  it("getFileBaselineProtectionWatchUrl returns SSE watch path", () => {
    expect(securityApi.getFileBaselineProtectionWatchUrl()).toBe(
      "/api/config/security/file-baseline/watch",
    );
  });
});
