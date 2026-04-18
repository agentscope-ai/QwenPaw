// ─── Skill Hub URL prefixes ───────────────────────────────────────────────────

export const SUPPORTED_SKILL_URL_PREFIXES = [
  "https://skills.sh/",
  "https://clawhub.ai/",
  "https://skillsmp.com/",
  "https://lobehub.com/",
  "https://market.lobehub.com/",
  "https://github.com/",
  "https://modelscope.cn/skills/",
];

export function isSupportedSkillUrl(url: string): boolean {
  return SUPPORTED_SKILL_URL_PREFIXES.some((prefix) => url.startsWith(prefix));
}

// ─── Search / filter ──────────────────────────────────────────────────────────

/** Prefix used to distinguish tag-filter tokens from plain text queries */
export const SKILL_TAG_FILTER_PREFIX = "tag:";
