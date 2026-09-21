import { request } from "@/api/request";

export interface Post {
  id: string;
  title: string;
  summary?: string;
  body_html?: string;
  body_text?: string;
  author_name?: string;
  article_type?: string;
  article_type_label?: string;
  published_at?: string;
  comment_count?: number;
  like_count?: number;
}
export interface Comment {
  id: string;
  author_name: string;
  content: string;
  created_at?: string;
  replies?: Comment[];
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
  detail: (id: string, signal?: AbortSignal) =>
    request<Post>(`/community/posts/${encodeURIComponent(id)}`, { signal }),
  comments: (id: string, page: number, signal?: AbortSignal) =>
    request<Page<Comment>>(
      `/community/posts/${encodeURIComponent(id)}/comments?page=${page}`,
      { signal },
    ),
  comment: (
    id: string,
    content: string,
    accountId: string,
    parentId?: string,
  ) =>
    request<Comment>(`/community/posts/${encodeURIComponent(id)}/comments`, {
      method: "POST",
      body: JSON.stringify({
        content,
        account_id: accountId,
        parent_id: parentId,
      }),
    }),
};
