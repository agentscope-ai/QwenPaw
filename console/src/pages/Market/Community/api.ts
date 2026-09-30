import { request } from "@/api/request";

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
  comment_count?: number;
  like_count?: number;
  favorite_count?: number;
  liked?: boolean;
  favorited?: boolean;
  author_avatar_url?: string;
  accepted_comment_ids?: string[];
  accepted_comment_id?: string;
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
  ) =>
    request<Comment>(`/community/posts/${encodeURIComponent(id)}/comments`, {
      method: "POST",
      body: JSON.stringify({
        content,
        account_id: accountId,
        parent_id: parentId,
        kind,
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
};
