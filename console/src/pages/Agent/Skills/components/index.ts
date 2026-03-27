export { SkillCard } from "./SkillCard";
export {
  SkillDrawer,
  parseFrontmatter,
  type SkillDrawerFormValues,
} from "./SkillDrawer";
export { getFileIcon, getSkillVisual } from "./SkillCard";
export {
  getSkillDisplaySource,
  getPoolBuiltinStatusLabel,
  getSkillSyncStatusLabel,
} from "./skillMetadata";
export { useConflictRenameModal } from "./useConflictRenameModal";
export { ImportHubModal } from "./ImportHubModal";
export { PoolTransferModal } from "./PoolTransferModal";

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
