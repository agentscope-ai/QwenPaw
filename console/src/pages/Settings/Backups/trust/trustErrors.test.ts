import { describe, it, expect, vi } from "vitest";
import { trustModeFromError, trustModeFromErrorCode } from "./trustErrors";

vi.mock("@/utils/error", () => ({
  parseErrorDetail: vi.fn(),
}));

import { parseErrorDetail } from "@/utils/error";

const mockedParseErrorDetail = vi.mocked(parseErrorDetail);

describe("trustModeFromErrorCode", () => {
  it("returns legacy for backup_legacy_unsigned", () => {
    expect(trustModeFromErrorCode("backup_legacy_unsigned")).toBe("legacy");
  });

  it("returns foreign for backup_signature_mismatch", () => {
    expect(trustModeFromErrorCode("backup_signature_mismatch")).toBe("foreign");
  });

  it("returns foreign for backup_unknown_signature_scheme", () => {
    expect(trustModeFromErrorCode("backup_unknown_signature_scheme")).toBe(
      "foreign",
    );
  });

  it("returns null for unknown codes", () => {
    expect(trustModeFromErrorCode("some_other_code")).toBeNull();
  });

  it("returns null for undefined / null codes", () => {
    expect(trustModeFromErrorCode(undefined)).toBeNull();
    expect(trustModeFromErrorCode(null)).toBeNull();
  });
});

describe("trustModeFromError", () => {
  it("returns the trust mode derived from the parsed error code", () => {
    mockedParseErrorDetail.mockReturnValue({ code: "backup_legacy_unsigned" });
    expect(trustModeFromError(new Error("boom"))).toBe("legacy");
  });

  it("returns null when the parsed error has no code", () => {
    mockedParseErrorDetail.mockReturnValue({});
    expect(trustModeFromError(new Error("boom"))).toBeNull();
  });

  it("returns null when parseErrorDetail yields null", () => {
    mockedParseErrorDetail.mockReturnValue(null);
    expect(trustModeFromError(new Error("boom"))).toBeNull();
  });
});
