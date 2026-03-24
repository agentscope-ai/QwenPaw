import type { SkillsMarketSpec } from "../api/types";

export const DEFAULT_SKILLS_MARKET_TEMPLATES: SkillsMarketSpec[] = [
  {
    id: "editor_skills",
    name: "Editor Skills",
    url: "https://github.com/futuremeng/editor-skills",
    branch: "main",
    path: "skills",
    enabled: true,
    order: 1,
    trust: "community",
  },
];

export function createDefaultSkillsMarketTemplates(): SkillsMarketSpec[] {
  return DEFAULT_SKILLS_MARKET_TEMPLATES.map((item) => ({ ...item }));
}
