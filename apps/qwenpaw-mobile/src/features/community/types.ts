export type CommunitySort = "recommended" | "latest";

export interface CommunityBadge {
  code: string;
  label: string;
  tier: number | null;
  badge_kind: string;
}

export interface CommunityArticleSummary {
  id: string;
  title: string;
  summary: string;
  tags: string[];
  status: string;
  liked: boolean;
  favorited: boolean;
  article_type: string;
  article_type_label: string;
  related_skill_ids: string[];
  related_plugin_ids: string[];
  cover_url: string | null;
  qa_status: "open" | "solved" | null;
  author_user_id: string;
  author_name: string;
  author_avatar_url: string | null;
  identity_badge: CommunityBadge | null;
  equipped_contribution_badge: CommunityBadge | null;
  is_featured: boolean;
  like_count: number;
  favorite_count: number;
  comment_count: number;
  view_count: number;
  published_at: string;
}

export interface CommunityArticle extends CommunityArticleSummary {
  body_text: string;
  body_html: string;
}

export interface CommunityComment {
  id: string;
  kind: "answer" | "comment";
  content: string;
  liked: boolean;
  accepted: boolean;
  replies: CommunityComment[];
  author_user_id: string;
  author_name: string;
  author_avatar_url: string | null;
  identity_badge: CommunityBadge | null;
  like_count: number;
  created_at: string;
}

export interface CommunityPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface CommunityArticleType {
  code: string;
  label: string;
}

export interface CommunityMeta {
  article_types: CommunityArticleType[];
  filter_types: CommunityArticleType[];
  fixed_tags: CommunityArticleType[];
}

export interface CommunityArticleDraft {
  title: string;
  articleType: string;
  body: string;
  tags: string[];
}

export interface CommunityArticlePayload {
  title: string;
  article_type: string;
  tags: string[];
  body_asl: string;
  body_html: string;
  body_text: string;
  related_skill_ids: string[];
  related_plugin_ids: string[];
}
