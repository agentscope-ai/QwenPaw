import { afterEach, describe, expect, it, vi } from "vitest";
import { creatorAuthenticatedUrl, creatorHeaders } from "../client";

afterEach(() => vi.unstubAllGlobals());

describe("Creator browser authentication", () => {
  it("keeps Hub account tokens out of native resource URLs", () => {
    vi.stubGlobal("QwenPaw", {
      host: {
        getApiToken: () => "account-secret",
        usesBrowserSession: () => true,
      },
    });
    expect(creatorAuthenticatedUrl("/events?project=one")).toBe(
      "/api/qwenpaw-creator/events?project=one",
    );
    expect(creatorHeaders().get("Authorization")).toBe("Bearer account-secret");
  });
  it("retains standalone native resource authentication", () => {
    vi.stubGlobal("QwenPaw", {
      host: {
        getApiToken: () => "account-secret",
        usesBrowserSession: () => false,
      },
    });
    expect(creatorAuthenticatedUrl("/video")).toBe(
      "/api/qwenpaw-creator/video?token=account-secret",
    );
  });
});
