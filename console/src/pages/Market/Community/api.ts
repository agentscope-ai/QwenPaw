import { request } from "@/api/request";
import { getApiUrl } from "@/api/config";
import { buildAuthHeaders } from "@/api/authHeaders";

export interface IdentityBadge {
  code: string;
  label: string;
  badge_kind?: "identity";
  tier?: null;
}

export interface Post {
  id: string;
  title: string;
  summary?: string;
  body_asl?: string;
  body_html?: string;
  body_text?: string;
  author_name?: string;
  author_user_id?: string;
  article_type?: string;
  article_type_label?: string;
  qa_status?: "open" | "solved" | null;
  published_at?: string;
  created_at?: string;
  comment_count?: number;
  like_count?: number;
  favorite_count?: number;
  liked?: boolean;
  favorited?: boolean;
  author_avatar_url?: string;
  cover_url?: string;
  view_count?: number;
  tags?: string[];
  accepted_answer_count?: number;
  accepted_comment_ids?: string[];
  accepted_comment_id?: string;
  related_skill_ids?: string[];
  related_plugin_ids?: string[];
  identity_badge?: IdentityBadge | null;
  identity_badges?: IdentityBadge[] | null;
}
export interface Comment {
  id: string;
  author_name: string;
  content: string;
  image_urls?: string[];
  created_at?: string;
  replies?: Comment[];
  kind?: "answer" | "comment";
  accepted?: boolean;
  liked?: boolean;
  like_count?: number;
  author_avatar_url?: string;
  author_user_id?: string;
  reply_to_user_display_name?: string;
  identity_badge?: IdentityBadge | null;
  identity_badges?: IdentityBadge[] | null;
}
export interface Page<T> {
  items: T[];
  total: number;
  pinned?: T[];
}
export const communityPostsApi = {
  list: (
    page: number,
    keyword: string,
    postType: string,
    sort: string,
    signal?: AbortSignal,
  ) =>
    request<Page<Post>>(
      `/community/posts?${new URLSearchParams({
        page: String(page),
        keyword,
        post_type: postType,
        sort,
      })}`,
      { signal },
    ),
  remove: (id: string, accountId: string) =>
    request(`/community/posts/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accountId }),
    }),
  update: (id: string, accountId: string, title: string, content: string) =>
    request<Post>(`/community/posts/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify({ account_id: accountId, title, content }),
    }),
  detail: (id: string, signal?: AbortSignal) =>
    request<Post>(`/community/posts/${encodeURIComponent(id)}`, { signal }),
  comments: (
    id: string,
    page: number,
    signal?: AbortSignal,
    kind?: "answer" | "comment",
  ) =>
    request<Page<Comment>>(
      `/community/posts/${encodeURIComponent(id)}/comments?page=${page}${
        kind ? `&kind=${kind}` : ""
      }`,
      { signal },
    ),
  comment: (
    id: string,
    content: string,
    accountId: string,
    parentId?: string,
    kind: "answer" | "comment" = "comment",
    mediaIds?: string[],
  ) =>
    request<Comment>(`/community/posts/${encodeURIComponent(id)}/comments`, {
      method: "POST",
      body: JSON.stringify({
        content,
        account_id: accountId,
        parent_id: parentId,
        kind,
        ...(mediaIds?.length ? { media_ids: mediaIds } : {}),
      }),
    }),
  interact: (id: string, action: "like" | "favorite", accountId: string) =>
    request<Partial<Post>>(
      `/community/posts/${encodeURIComponent(id)}/interactions/${action}`,
      {
        method: "POST",
        body: JSON.stringify({ account_id: accountId }),
      },
    ),
  likeComment: (id: string, accountId: string) =>
    request<Partial<Comment>>(
      `/community/comments/${encodeURIComponent(id)}/like`,
      {
        method: "POST",
        body: JSON.stringify({ account_id: accountId }),
      },
    ),
  acceptComment: (postId: string, commentId: string, accountId: string) =>
    request<Partial<Post>>(
      `/community/posts/${encodeURIComponent(
        postId,
      )}/comments/${encodeURIComponent(commentId)}/accept`,
      {
        method: "POST",
        body: JSON.stringify({ account_id: accountId }),
      },
    ),
  unacceptComment: (postId: string, commentId: string, accountId: string) =>
    request<Partial<Post>>(
      `/community/posts/${encodeURIComponent(
        postId,
      )}/comments/${encodeURIComponent(commentId)}/accept`,
      {
        method: "DELETE",
        body: JSON.stringify({ account_id: accountId }),
      },
    ),
};
export interface RelatedResource {
  id: string;
  title: string;
  versionLabel?: string;
  description?: string;
  iconUrl?: string;
}
export const communityRelatedApi = {
  skill: (id: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>(
      `/community/skills/${encodeURIComponent(id)}`,
      { signal },
    ),
  plugin: (id: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>(
      `/community/plugins/${encodeURIComponent(id)}`,
      { signal },
    ),
};
export interface CommunityMedia {
  media_id: string;
  url: string;
}
export const communityMediaApi = {
  // Multipart upload bypasses the json request helper so fetch can set the
  // boundary itself; mirrors plugin.ts uploadPlugin.
  upload: async (
    file: File,
    accountId: string,
    purpose: "comment" | "body" = "comment",
  ): Promise<CommunityMedia> => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(
      getApiUrl(
        `/community/media?purpose=${purpose}&account_id=${encodeURIComponent(
          accountId,
        )}`,
      ),
      { method: "POST", headers: buildAuthHeaders(), body: form },
    );
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ?? `Upload failed (${response.status})`);
    }
    return (await response.json()) as CommunityMedia;
  },
  remove: (mediaId: string, accountId: string) =>
    request<null>(
      `/community/media/${encodeURIComponent(
        mediaId,
      )}?account_id=${encodeURIComponent(accountId)}`,
      { method: "DELETE" },
    ),
};
