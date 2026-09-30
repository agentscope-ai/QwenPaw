export const QWENPAW_COMMUNITY_URL = "https://platform.agentscope.io/community";

export const COMMUNITY_POST_TYPES = [
  "question",
  "work_share",
  "app_case",
  "beginner_tutorial",
  "discussion",
] as const;
export const COMMUNITY_FILTER_TYPES = [
  "all",
  ...COMMUNITY_POST_TYPES,
  "official_announcement",
] as const;
export const COMMUNITY_SORTS = ["recommended", "latest"] as const;
