import type { ReportResource } from "@/api/modules/communityReport";
import { COMMUNITY_POST_TYPES } from "@/constants/community";

export interface DraftContent {
  title: string;
  content: string;
  type: string;
  resources: ReportResource[];
  instructions?: string;
  media?: { url: string; media_id: string }[];
}
export interface PostDraft extends DraftContent {
  id: string;
  updatedAt: number;
}
const key = (account: string) => `qwenpaw.community.drafts.v1:${account}`;

export function listPostDrafts(account: string): PostDraft[] {
  const items: unknown = JSON.parse(localStorage.getItem(key(account)) || "[]");
  if (!Array.isArray(items)) throw new Error("invalid_drafts");
  if (
    items.some(
      (item) =>
        !item ||
        typeof item.id !== "string" ||
        typeof item.title !== "string" ||
        typeof item.content !== "string" ||
        !COMMUNITY_POST_TYPES.includes(item.type) ||
        !Array.isArray(item.resources) ||
        item.resources.some(
          (resource: ReportResource) =>
            !resource?.origin ||
            typeof resource.name !== "string" ||
            typeof resource.origin.resource_id !== "string" ||
            !["plugin", "app", "skill"].includes(resource.origin.resource_type),
        ) ||
        (item.instructions !== undefined &&
          typeof item.instructions !== "string") ||
        (item.media !== undefined &&
          (!Array.isArray(item.media) ||
            item.media.some(
              (media: { url: string; media_id: string }) =>
                !media ||
                typeof media.url !== "string" ||
                typeof media.media_id !== "string",
            ))) ||
        typeof item.updatedAt !== "number",
    )
  )
    throw new Error("invalid_drafts");
  return items.sort((a, b) => b.updatedAt - a.updatedAt);
}

export function savePostDraft(
  account: string,
  content: DraftContent,
  id?: string,
): PostDraft {
  const items = listPostDrafts(account);
  const draft = {
    ...content,
    id: id || crypto.randomUUID(),
    updatedAt: Date.now(),
  };
  const others = items.filter((item) => item.id !== draft.id);
  if (others.length >= 50) throw new Error("draft_limit");
  localStorage.setItem(key(account), JSON.stringify([draft, ...others]));
  return draft;
}

export function removePostDraft(account: string, id: string) {
  localStorage.setItem(
    key(account),
    JSON.stringify(listPostDrafts(account).filter((item) => item.id !== id)),
  );
}
