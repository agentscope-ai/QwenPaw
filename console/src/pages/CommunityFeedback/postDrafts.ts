import { request } from "@/api/request";
import { removeWritingDraftSessions } from "./writingSession";
import type {
  DraftContent,
  PostDraft as StoredDraft,
} from "./legacyPostDrafts";
export type { DraftContent } from "./legacyPostDrafts";
export interface PostDraft extends StoredDraft {
  editable?: boolean;
}
interface PlatformDraft extends Omit<PostDraft, "updatedAt"> {
  updated_at?: string;
}
const normalize = (draft: PlatformDraft): PostDraft => ({
  ...draft,
  updatedAt: draft.updated_at ? Date.parse(draft.updated_at) : Date.now(),
});
export async function listPostDrafts(account: string, page = 1) {
  const result = await request<{ items: PlatformDraft[]; total: number }>(
    `/community/drafts?account_id=${encodeURIComponent(account)}&page=${page}`,
  );
  return { items: result.items.map(normalize), total: result.total };
}
export async function getPostDraft(account: string, id: string) {
  return normalize(
    await request<PlatformDraft>(
      `/community/drafts/${encodeURIComponent(
        id,
      )}?account_id=${encodeURIComponent(account)}`,
    ),
  );
}
export async function savePostDraft(
  account: string,
  content: DraftContent,
  id?: string,
): Promise<PostDraft> {
  const result = await request<{ id: string }>("/community/drafts", {
    method: "PUT",
    body: JSON.stringify({
      account_id: account,
      draft_id: id,
      title: content.title,
      content: content.content,
      article_type: content.type,
      origins: content.resources.map((item) => item.origin),
      media_ids: (content.media || [])
        .filter((item) => content.content.includes(item.url))
        .map((item) => item.media_id),
    }),
  });
  return { ...content, id: result.id, updatedAt: Date.now() };
}
export async function removePostDraft(account: string, id: string) {
  await request(`/community/drafts/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account_id: account }),
  });
  removeWritingDraftSessions(account, id);
}
