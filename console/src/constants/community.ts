export const QWENPAW_COMMUNITY_URL = "https://platform.agentscope.io/community";

export const COMMUNITY_POST_TYPES = [
  "question",
  "work_share",
  "app_case",
  "beginner_tutorial",
  "discussion",
] as const;
export type CommunityPostType = (typeof COMMUNITY_POST_TYPES)[number];
// Display order of the category chips above the feed.
export const COMMUNITY_FILTER_TYPES = [
  "all",
  "question",
  "beginner_tutorial",
  "work_share",
  "app_case",
  "discussion",
  "official_announcement",
] as const;
export const COMMUNITY_SORTS = ["recommended", "latest", "waiting"] as const;
export type CommunitySort = (typeof COMMUNITY_SORTS)[number];
/** Sort tabs available per category (mirrors agentscope-platform-front). */
export function communitySortsForType(type: string): CommunitySort[] {
  if (type === "official_announcement") return ["recommended"];
  if (type === "all" || type === "question")
    return ["recommended", "latest", "waiting"];
  return ["recommended", "latest"];
}

/** Post entry shown next to the feed search, mirroring the Platform feed. */
export type CommunityPostAction =
  | { kind: "menu"; labelKey: string }
  | { kind: "ask"; labelKey: string }
  | {
      kind: "write";
      articleType: CommunityPostType;
      labelKey: string;
    };

export function communityPostActionForType(
  type: string,
): CommunityPostAction | null {
  switch (type) {
    case "all":
      return { kind: "menu", labelKey: "communityPage.postEntry" };
    case "question":
      return { kind: "ask", labelKey: "communityPage.askEntry" };
    case "beginner_tutorial":
      return {
        kind: "write",
        articleType: "beginner_tutorial",
        labelKey: "communityPage.writeTutorial",
      };
    case "work_share":
      return {
        kind: "write",
        articleType: "work_share",
        labelKey: "communityPage.writeShare",
      };
    case "app_case":
      return {
        kind: "write",
        articleType: "app_case",
        labelKey: "communityPage.writeCase",
      };
    case "discussion":
      return {
        kind: "write",
        articleType: "discussion",
        labelKey: "communityPage.writeDiscussion",
      };
    default:
      return null;
  }
}
