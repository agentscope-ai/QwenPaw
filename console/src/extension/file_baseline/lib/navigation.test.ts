import { describe, it, expect } from "vitest";
import {
  resolveFileBaselineDriftDeepLink,
  resolveFileBaselineDriftNavigation,
} from "./navigation";

describe("personaNavigation", () => {
  it("prefers payload deep_link when present", () => {
    expect(
      resolveFileBaselineDriftDeepLink({
        deep_link:
          "/security?tab=integrityProtection&fileBaselineAlertId=alert-from-inbox",
        alert_id: "alert-from-inbox",
      }),
    ).toBe("/security?tab=integrityProtection&fileBaselineAlertId=alert-from-inbox");
  });

  it("builds integrity check link from alert_id fallback", () => {
    expect(
      resolveFileBaselineDriftDeepLink({
        alert_id: "alert-xyz",
      }),
    ).toBe("/security?tab=integrityProtection&fileBaselineAlertId=alert-xyz");
  });

  it("returns null for non-persona events", () => {
    expect(
      resolveFileBaselineDriftNavigation("heartbeat", {
        alert_id: "ignored",
      }),
    ).toBeNull();
  });

  it("returns deep link for file_baseline_drift event type", () => {
    expect(
      resolveFileBaselineDriftNavigation("file_baseline_drift", {
        deep_link:
          "/security?tab=integrityProtection&fileBaselineAlertId=alert-from-inbox",
      }),
    ).toBe("/security?tab=integrityProtection&fileBaselineAlertId=alert-from-inbox");
  });
});
