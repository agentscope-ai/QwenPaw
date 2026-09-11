/**
 * Tests for constants/skill.
 *
 * Covers:
 * - SUPPORTED_SKILL_URL_PREFIXES array structure
 * - isSupportedSkillUrl() happy path and edge cases
 * - SKILL_TAG_FILTER_PREFIX value
 */
import { describe, it, expect } from "vitest";
import {
  SUPPORTED_SKILL_URL_PREFIXES,
  isSupportedSkillUrl,
  SKILL_TAG_FILTER_PREFIX,
} from "./skill";

describe("SUPPORTED_SKILL_URL_PREFIXES", () => {
  it("is a non-empty array of URL prefixes", () => {
    expect(Array.isArray(SUPPORTED_SKILL_URL_PREFIXES)).toBe(true);
    expect(SUPPORTED_SKILL_URL_PREFIXES.length).toBeGreaterThan(0);
  });

  it("contains only https URLs", () => {
    for (const prefix of SUPPORTED_SKILL_URL_PREFIXES) {
      expect(prefix).toMatch(/^https:\/\//);
    }
  });
});

describe("isSupportedSkillUrl", () => {
  it.each([
    [
      "qwenpaw readable URL",
      "https://platform.agentscope.io/skills/@user/qwenpaw-docs-zh",
      true,
    ],
    [
      "qwenpaw detail URL",
      "https://platform.agentscope.io/skills/019f5c27-c57d-7584-8617-9bf93c383950",
      true,
    ],
    ["skills.sh URL", "https://skills.sh/my-skill", true],
    ["clawhub URL", "https://clawhub.ai/skill", true],
    ["github URL", "https://github.com/user/repo", true],
    ["modelscope URL", "https://modelscope.cn/skills/my-skill", true],
    ["unsupported domain", "https://example.com/skill", false],
    ["http (not https)", "http://skills.sh/my-skill", false],
    ["empty string", "", false],
    ["partial prefix match", "https://skills.sh.other.com/skill", false],
    [
      "qwenpaw lookalike domain",
      "https://platform.agentscope.io.example.com/skills/my-skill",
      false,
    ],
  ])("returns %s for %s → %s", (_, url, expected) => {
    expect(isSupportedSkillUrl(url)).toBe(expected);
  });
});

describe("SKILL_TAG_FILTER_PREFIX", () => {
  it('is "tag:"', () => {
    expect(SKILL_TAG_FILTER_PREFIX).toBe("tag:");
  });
});
