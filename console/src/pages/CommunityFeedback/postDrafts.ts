import { request } from "@/api/request";
import { removeWritingDraftSessions } from "./writingSession";
import { splitReportResources } from "@/utils/communityResources";
import { normalizeGithubLink } from "@/pages/Market/Community/githubLink";
import type {
  DraftContent,
  PostDraft as StoredDraft,
} from "./legacyPostDrafts";
export type { DraftContent } from "./legacyPostDrafts";
export interface PostDraft extends StoredDraft {
  editable?: boolean;
  /** One-line content preview carried by the Platform draft list. */
  summary?: string;
}
interface PlatformDraft extends Omit<PostDraft, "updatedAt"> {
  updated_at?: string;
  github_link?: string | null;
}
const normalize = (draft: PlatformDraft): PostDraft => ({
  ...draft,
  summary: draft.summary ?? "",
  // Guard against corrupt payloads: a non-string link would throw inside
  // savePostDraft and break the whole draft path for the account.
  githubLink:
    typeof draft.github_link === "string"
      ? draft.github_link
      : typeof draft.githubLink === "string"
      ? draft.githubLink
      : "",
  updatedAt: draft.updated_at ? Date.parse(draft.updated_at) : Date.now(),
});
export async function listPostDrafts(
  account: string,
  page = 1,
  type?: "article" | "question",
) {
  const query = new URLSearchParams({
    account_id: account,
    page: String(page),
  });
  // Mirrors Platform's getMyDrafts type filter; omit it to list every draft.
  if (type) query.set("draft_type", type);
  const result = await request<{ items: PlatformDraft[]; total: number }>(
    `/community/drafts?${query}`,
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
      ...splitReportResources(content.resources),
      github_link: normalizeGithubLink(content.githubLink || ""),
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
