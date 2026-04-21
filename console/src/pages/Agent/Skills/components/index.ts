export { SkillCard } from "./SkillCard";
export {
  SkillDrawer,
  parseFrontmatter,
  MAX_TAGS,
  MAX_TAG_LENGTH,
  type SkillDrawerFormValues,
} from "./SkillDrawer";
export { getFileIcon, getSkillVisual } from "./SkillCard";
export {
  getSkillDisplaySource,
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
} from "@/utils/skill";
export { useConflictRenameModal } from "./useConflictRenameModal";
export { ImportHubModal } from "./ImportHubModal";
export { PoolTransferModal } from "./PoolTransferModal";
export { SkillFilterDropdown, TAG_PREFIX } from "./SkillFilterDropdown";
export { HeaderActions } from "./HeaderActions";
export { SkillsToolbar } from "./SkillsToolbar";
export { SkillListItem } from "./SkillListItem";

export {
  SUPPORTED_SKILL_URL_PREFIXES,
  isSupportedSkillUrl,
} from "@/constants/skill";

export interface SkillMarket {
  key: string;
  name: string;
  homepage: string;
  urlPrefix: string;
  examples: { label: string; url: string }[];
}

export const skillMarkets: SkillMarket[] = [
  {
    key: "skills.sh",
    name: "Skills.sh",
    homepage: "https://skills.sh",
    urlPrefix: "https://skills.sh/",
    examples: [
      {
        label: "find-skills",
        url: "https://skills.sh/vercel-labs/skills/find-skills",
      },
    ],
  },
  {
    key: "clawhub",
    name: "ClawHub",
    homepage: "https://clawhub.ai",
    urlPrefix: "https://clawhub.ai/",
    examples: [
      { label: "word-docx", url: "https://clawhub.ai/ivangdavila/word-docx" },
      { label: "excel-xlsx", url: "https://clawhub.ai/ivangdavila/excel-xlsx" },
    ],
  },
  {
    key: "skillsmp",
    name: "SkillsMP",
    homepage: "https://skillsmp.com",
    urlPrefix: "https://skillsmp.com/",
    examples: [
      {
        label: "skill-creator",
        url: "https://skillsmp.com/skills/anthropics-skills-skills-skill-creator-skill-md",
      },
    ],
  },
  {
    key: "lobehub",
    name: "LobeHub",
    homepage: "https://lobehub.com/it/skills",
    urlPrefix: "https://lobehub.com/",
    examples: [
      {
        label: "cli-developer",
        url: "https://lobehub.com/zh/skills/openclaw-skills-cli-developer",
      },
    ],
  },
  {
    key: "market.lobehub",
    name: "LobeHub Market",
    homepage: "https://market.lobehub.com",
    urlPrefix: "https://market.lobehub.com/",
    examples: [
      {
        label: "cli-developer",
        url: "https://market.lobehub.com/api/v1/skills/openclaw-skills-cli-developer/download",
      },
    ],
  },
  {
    key: "github",
    name: "GitHub",
    homepage: "https://github.com",
    urlPrefix: "https://github.com/",
    examples: [
      {
        label: "skill-creator",
        url: "https://github.com/anthropics/skills/tree/main/skills/skill-creator",
      },
    ],
  },
  {
    key: "modelscope",
    name: "ModelScope",
    homepage: "https://modelscope.cn/skills",
    urlPrefix: "https://modelscope.cn/skills/",
    examples: [
      {
        label: "skill-creator",
        url: "https://modelscope.cn/skills/@anthropics/skill-creator",
      },
    ],
  },
];
