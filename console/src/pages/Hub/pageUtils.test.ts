import { describe, expect, it } from "vitest";
import { dockerReferenceParts, formatDate, formatImageSize } from "./pageUtils";

// ---------------------------------------------------------------------------
// formatDate — regression for #1395
// (dates stayed in English format after switching the UI language to Chinese;
// the contract is: the formatted output follows the given language)
// ---------------------------------------------------------------------------
describe("formatDate (#1395)", () => {
  const ISO = "2026-03-15T08:05:00";

  it("formats in Chinese style when language is zh", () => {
    const out = formatDate(ISO, "zh-CN");
    // Chinese short-month format renders as e.g. "3月15日 08:05"
    expect(out).toContain("月");
    expect(out).toContain("15");
    expect(out).toContain("08:05");
  });

  it("formats in English style when language is en", () => {
    const out = formatDate(ISO, "en-US");
    expect(out).toContain("Mar");
    expect(out).toContain("15");
  });

  it("output changes when the language changes", () => {
    // The core regression of #1395: language switch must actually change
    // the rendered format, not stay stuck in one locale.
    expect(formatDate(ISO, "zh-CN")).not.toBe(formatDate(ISO, "en-US"));
  });
});

// ---------------------------------------------------------------------------
// formatImageSize / dockerReferenceParts — pure functions in the same module
// ---------------------------------------------------------------------------
describe("formatImageSize", () => {
  it("returns dash for zero size", () => {
    expect(formatImageSize(0)).toBe("—");
  });

  it("formats bytes / KB / MB / GB (KB whole, MB+ one decimal)", () => {
    expect(formatImageSize(512)).toBe("512 B");
    expect(formatImageSize(1024)).toBe("1 KB");
    expect(formatImageSize(1536)).toBe("2 KB");
    expect(formatImageSize(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatImageSize(2 * 1024 * 1024 * 1024)).toBe("2.0 GB");
  });

  it("caps at GB for very large sizes", () => {
    expect(formatImageSize(10 * 1024 ** 4)).toBe("10240.0 GB");
  });
});

describe("dockerReferenceParts", () => {
  it("splits repository and tag", () => {
    expect(dockerReferenceParts("nginx:1.25")).toEqual({
      repository: "nginx",
      tag: "1.25",
    });
  });

  it("defaults tag to latest when absent", () => {
    expect(dockerReferenceParts("nginx")).toEqual({
      repository: "nginx",
      tag: "latest",
    });
  });

  it("keeps registry path in repository and ignores digest", () => {
    expect(
      dockerReferenceParts("registry.example.com/team/app:v2@sha256:abcdef"),
    ).toEqual({ repository: "registry.example.com/team/app", tag: "v2" });
  });

  it("handles registry with port but no tag", () => {
    // The colon in host:port must not be mistaken for a tag separator.
    expect(dockerReferenceParts("registry.example.com:5000/app")).toEqual({
      repository: "registry.example.com:5000/app",
      tag: "latest",
    });
  });
});
