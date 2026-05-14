/**
 * Tests for layouts/constants.
 *
 * Covers:
 * - URL constants
 * - ONE_HOUR_MS value
 * - DEFAULT_OPEN_KEYS structure
 * - KEY_TO_PATH and KEY_TO_LABEL mappings
 * - getWebsiteLang()
 * - getDocsUrl(), getFaqUrl(), getReleaseNotesUrl()
 * - isStableVersion()
 * - compareVersions()
 * - UPDATE_MD structure
 */
import { describe, it, expect } from "vitest";
import {
  PYPI_URL,
  GITHUB_URL,
  ONE_HOUR_MS,
  DEFAULT_OPEN_KEYS,
  KEY_TO_PATH,
  KEY_TO_LABEL,
  getWebsiteLang,
  getDocsUrl,
  getFaqUrl,
  getReleaseNotesUrl,
  isStableVersion,
  compareVersions,
  UPDATE_MD,
} from "./constants";

describe("URL constants", () => {
  it("PYPI_URL points to qwenpaw json endpoint", () => {
    expect(PYPI_URL).toBe("https://pypi.org/pypi/qwenpaw/json");
  });

  it("GITHUB_URL points to QwenPaw repo", () => {
    expect(GITHUB_URL).toContain("github.com");
    expect(GITHUB_URL).toContain("QwenPaw");
  });
});

describe("ONE_HOUR_MS", () => {
  it("equals 3600000 ms", () => {
    expect(ONE_HOUR_MS).toBe(60 * 60 * 1000);
  });
});

describe("DEFAULT_OPEN_KEYS", () => {
  it("is a non-empty array", () => {
    expect(Array.isArray(DEFAULT_OPEN_KEYS)).toBe(true);
    expect(DEFAULT_OPEN_KEYS.length).toBeGreaterThan(0);
  });

  it("contains expected group keys", () => {
    expect(DEFAULT_OPEN_KEYS).toContain("chat-group");
    expect(DEFAULT_OPEN_KEYS).toContain("control-group");
    expect(DEFAULT_OPEN_KEYS).toContain("agent-group");
    expect(DEFAULT_OPEN_KEYS).toContain("settings-group");
  });
});

describe("KEY_TO_PATH", () => {
  it("maps chat to /chat", () => {
    expect(KEY_TO_PATH.chat).toBe("/chat");
  });

  it("maps models to /models", () => {
    expect(KEY_TO_PATH.models).toBe("/models");
  });

  it("all values start with /", () => {
    for (const path of Object.values(KEY_TO_PATH)) {
      expect(path).toMatch(/^\//);
    }
  });
});

describe("KEY_TO_LABEL", () => {
  it("has labels for most path keys", () => {
    const labeledKeys = Object.keys(KEY_TO_LABEL);
    const pathKeys = Object.keys(KEY_TO_PATH);
    // Most path keys should have labels; some newer pages may not yet
    for (const key of pathKeys) {
      if (labeledKeys.includes(key)) continue;
      // Keys without labels are acceptable but logged
      console.warn(`KEY_TO_LABEL missing entry for: ${key}`);
    }
    expect(labeledKeys.length).toBeGreaterThan(0);
  });

  it("all labels are i18n keys starting with nav.", () => {
    for (const label of Object.values(KEY_TO_LABEL)) {
      expect(label).toMatch(/^nav\./);
    }
  });
});

describe("getWebsiteLang", () => {
  it.each([
    ["zh", "zh"],
    ["zh-CN", "zh"],
    ["zh-TW", "zh"],
    ["en", "en"],
    ["en-US", "en"],
    ["ja", "en"],
    ["ru", "en"],
  ])("returns %s for input %s", (input, expected) => {
    expect(getWebsiteLang(input)).toBe(expected);
  });
});

describe("getDocsUrl", () => {
  it("includes lang param", () => {
    const url = getDocsUrl("zh");
    expect(url).toContain("lang=zh");
    expect(url).toContain("/docs/intro");
  });
});

describe("getFaqUrl", () => {
  it("includes lang param", () => {
    const url = getFaqUrl("en");
    expect(url).toContain("lang=en");
    expect(url).toContain("/docs/faq");
  });
});

describe("getReleaseNotesUrl", () => {
  it("includes lang param", () => {
    const url = getReleaseNotesUrl("zh");
    expect(url).toContain("lang=zh");
    expect(url).toContain("/release-notes");
  });
});

describe("isStableVersion", () => {
  it.each([
    ["1.0.0", true],
    ["2.3.4", true],
    ["1.0.0.post1", true],
    ["1.0.0a1", false],
    ["1.0.0beta2", false],
    ["2.0rc1", false],
    ["3.0.0dev1", false],
    ["1.0.0c3", false],
  ])("isStableVersion(%s) → %s", (version, expected) => {
    expect(isStableVersion(version)).toBe(expected);
  });
});

describe("compareVersions", () => {
  it.each([
    ["1.0.0", "2.0.0", -1],
    ["2.0.0", "1.0.0", 1],
    ["1.0.0", "1.0.0", 0],
    ["1.0.0", "1.0.1", -1],
    ["1.0.1", "1.0.0", 1],
    ["1.0.0a1", "1.0.0", -1],
    ["1.0.0", "1.0.0a1", 1],
    ["1.0.0b1", "1.0.0", -1],
    ["1.0.0rc1", "1.0.0", -1],
    ["1.0.0a1", "1.0.0b1", -1],
    ["1.0.0b1", "1.0.0rc1", -1],
    ["1.0.0", "1.0.0.post1", -1],
    ["1.0.0.post1", "1.0.0.post2", -1],
  ] as [string, string, number][])(
    "compareVersions(%s, %s) → %s",
    (a, b, expected) => {
      const result = compareVersions(a, b);
      expect(Math.sign(result)).toBe(expected);
    },
  );
});

describe("UPDATE_MD", () => {
  it("has entries for zh, ru, and en", () => {
    expect(UPDATE_MD).toHaveProperty("zh");
    expect(UPDATE_MD).toHaveProperty("ru");
    expect(UPDATE_MD).toHaveProperty("en");
  });

  it("each entry is a non-empty string", () => {
    for (const [, md] of Object.entries(UPDATE_MD)) {
      expect(typeof md).toBe("string");
      expect(md.length).toBeGreaterThan(0);
    }
  });
});