import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../src/api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));

import {
  fetchAuthMeta,
  parseAuthMeta,
  sendSmsCode,
} from "../../../src/auth/proboost/client";

describe("proboost auth metadata client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("parses backend metadata and keeps option order aligned with supported codes", () => {
    expect(
      parseAuthMeta({
        defaultCountryCode: "+44",
        supportedCountryCodes: ["+44", "+86", "+44"],
        countryCodeOptions: [
          { value: "+86", labelKey: "auth.countryCodeOptions.cn" },
          { value: "+44" },
          { value: "+1", labelKey: "ignored.extra.option" },
        ],
      }),
    ).toEqual({
      defaultCountryCode: "+44",
      supportedCountryCodes: ["+44", "+86"],
      countryCodeOptions: [
        { value: "+44" },
        { value: "+86", labelKey: "auth.countryCodeOptions.cn" },
      ],
    });
  });

  it("fetches auth metadata from the backend proxy and returns normalized data", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        defaultCountryCode: "+39",
        supportedCountryCodes: ["+86", "+39"],
        countryCodeOptions: [
          { value: "+39", labelKey: "auth.countryCodeOptions.it" },
          { value: "+86", labelKey: "auth.countryCodeOptions.cn" },
        ],
      }),
    } as Response);

    await expect(fetchAuthMeta()).resolves.toEqual({
      defaultCountryCode: "+39",
      supportedCountryCodes: ["+86", "+39"],
      countryCodeOptions: [
        { value: "+86", labelKey: "auth.countryCodeOptions.cn" },
        { value: "+39", labelKey: "auth.countryCodeOptions.it" },
      ],
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/proboost-auth/meta", {
      method: "GET",
      credentials: "include",
    });
  });

  it("throws when the metadata request fails", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      json: async () => ({ message: "down" }),
    } as Response);

    await expect(fetchAuthMeta()).rejects.toThrow(
      "Request failed: 503 Service Unavailable",
    );
  });

  it("posts SMS requests through the backend proxy instead of the upstream ProBoost domain", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        success: true,
        code: "0",
        msg: "ok",
        data: true,
      }),
    } as Response);

    await expect(
      sendSmsCode({
        countryCode: "+86",
        phone: "13800138000",
        channelCode: null,
        deepSeekChannelCode: null,
      }),
    ).resolves.toMatchObject({
      success: true,
      code: "0",
      data: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/proboost-auth/send-sms-code",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      }),
    );
  });
});

