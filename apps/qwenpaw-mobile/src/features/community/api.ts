import { platformRequest } from "../../api/platform";
import { buildCommunityArticlePayload } from "./model";
import type {
  CommunityArticle,
  CommunityArticleDraft,
  CommunityArticleSummary,
  CommunityComment,
  CommunityMeta,
  CommunityPage,
  CommunitySort,
} from "./types";

const PLATFORM_API = "https://platform.agentscope.io/api/v1/community";

interface PlatformEnvelope<T> {
  data: T;
  request_id?: string;
}

export interface ListCommunityOptions {
  page: number;
  pageSize: number;
  sort: CommunitySort;
  type?: string;
}

export async function listCommunityArticles(
  options: ListCommunityOptions,
): Promise<CommunityPage<CommunityArticleSummary>> {
  const params = new URLSearchParams({
    page: String(options.page),
    page_size: String(options.pageSize),
    sort: options.sort,
  });
  if (options.type) params.set("type", options.type);
  return platformCommunityRequest(`/articles?${params.toString()}`);
}

export function getCommunityMeta(): Promise<CommunityMeta> {
  return platformCommunityRequest("/meta");
}

export function getCommunityArticle(
  articleId: string,
): Promise<CommunityArticle> {
  return platformCommunityRequest(
    `/articles/${encodeURIComponent(articleId)}`,
  );
}

export function getCommunityComments(
  articleId: string,
): Promise<CommunityPage<CommunityComment>> {
  return platformCommunityRequest(
    `/articles/${encodeURIComponent(articleId)}/comments?page=1&page_size=50`,
  );
}

export function communityArticleUrl(articleId: string): string {
  return `https://platform.agentscope.io/community/articles/${encodeURIComponent(articleId)}`;
}

export const communityWriteUrl =
  "https://platform.agentscope.io/community/write";

export function likeCommunityArticle(
  articleId: string,
): Promise<CommunityArticleSummary> {
  return platformRequest(
    `/api/v1/community/articles/${encodeURIComponent(articleId)}/like`,
    { method: "POST" },
  );
}

export function createCommunityComment(
  articleId: string,
  content: string,
): Promise<CommunityComment> {
  return platformRequest(
    `/api/v1/community/articles/${encodeURIComponent(articleId)}/comments`,
    {
      method: "POST",
      body: JSON.stringify({
        content: content.trim(),
        parent_id: null,
        kind: "comment",
        media_ids: [],
      }),
    },
  );
}

export function publishCommunityArticle(
  draft: CommunityArticleDraft,
): Promise<CommunityArticle> {
  return platformRequest("/api/v1/community/articles", {
    method: "POST",
    body: JSON.stringify(buildCommunityArticlePayload(draft)),
  });
}

async function platformCommunityRequest<T>(path: string): Promise<T> {
  const response = await fetch(`${PLATFORM_API}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Platform 社区暂时不可用（${response.status}）`);
  }
  const payload = await response.json() as PlatformEnvelope<T>;
  return payload.data;
}
