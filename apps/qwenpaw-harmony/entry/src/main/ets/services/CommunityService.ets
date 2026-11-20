/*
 * 社区（Platform）—— 移植 PR #7378 features/community/{types,model,api}.ts。
 *   读接口（列表 / 元数据 / 详情 / 评论）走公开读，不需要登录；
 *   写接口（点赞 / 评论 / 发布）需要 AgentScope Platform 会话。
 * 数据源：{Platform}/api/v1/community/*（信封 { data: ... }）。
 */

import { http } from '@kit.NetworkKit';
import { Context } from '@kit.AbilityKit';
import { platformPublicRequest, platformRequest, PLATFORM_BASE_URL } from './PlatformSession';
import { objOf, strOf, numOf, boolOf, strArrOf } from './JsonUtil';
import { t, tf } from './I18n';

export interface CommunityBadge {
  code: string;
  label: string;
  tier: number;
  badgeKind: string;
}

export interface CommunityArticleSummary {
  id: string;
  title: string;
  summary: string;
  tags: string[];
  liked: boolean;
  favorited: boolean;
  articleType: string;
  articleTypeLabel: string;
  relatedSkillIds: string[];
  relatedPluginIds: string[];
  coverUrl: string;
  qaStatus: string;      // 'open' | 'solved' | ''
  authorName: string;
  authorAvatarUrl: string;
  identityBadge: CommunityBadge | null;
  isFeatured: boolean;
  likeCount: number;
  favoriteCount: number;
  commentCount: number;
  viewCount: number;
  publishedAt: string;
}

export interface CommunityArticlePage {
  items: CommunityArticleSummary[];
  total: number;
  page: number;
  pageSize: number;
}

export interface CommunityComment {
  id: string;
  kind: string;         // 'answer' | 'comment'
  content: string;
  liked: boolean;
  accepted: boolean;
  replies: CommunityComment[];
  authorName: string;
  authorAvatarUrl: string;
  likeCount: number;
  createdAt: string;
}

export interface CommunityCommentPage {
  items: CommunityComment[];
  total: number;
}

export interface CommunityArticleType {
  code: string;
  label: string;
}

export interface CommunityMeta {
  filterTypes: CommunityArticleType[];
  fixedTags: CommunityArticleType[];
}

export interface CommunityArticleDraft {
  title: string;
  articleType: string;
  body: string;
  tags: string[];
}

// ============ 模型（对齐 7378 features/community/model.ts）============

// 头像占位首字母：多词取前两词首字母，单词取前两字符
export function communityInitials(name: string): string {
  const normalized: string = name.trim();
  if (normalized.length === 0) {
    return 'QP';
  }
  const words: string[] = normalized.split(' ').filter((w: string) => w.length > 0);
  if (words.length > 1) {
    return (words[0].charAt(0) + words[1].charAt(0)).toUpperCase();
  }
  return normalized.substring(0, 2).toUpperCase();
}

// 相对时间：刚刚 / n 分钟前 / n 小时前 / 月-日（对齐 7378 formatCommunityDate）
export function formatCommunityDate(value: string): string {
  const ms: number = Date.parse(value);
  if (!isFinite(ms)) {
    return '';
  }
  const elapsed: number = Date.now() - ms;
  const minute: number = 60000;
  const hour: number = 3600000;
  const day: number = 86400000;
  if (elapsed >= 0 && elapsed < minute) {
    return t($r('app.string.time_just_now'));
  }
  if (elapsed >= 0 && elapsed < hour) {
    return tf($r('app.string.time_minutes_ago'), Math.floor(elapsed / minute));
  }
  if (elapsed >= 0 && elapsed < day) {
    return tf($r('app.string.time_hours_ago'), Math.floor(elapsed / hour));
  }
  const d: Date = new Date(ms);
  return tf($r('app.string.date_month_day'), d.getMonth() + 1, d.getDate());
}

// 去表情 + 折叠空白（对齐 7378 removeCommunityEmoji / normalizeCommunityText）。
// 除 Unicode 表情码点外，还要去掉正文里以 `[emoji:<url>]` 形式出现的表情占位：Platform 侧的正文
// 会把表情节点写成这种占位（其 url 指向图片资源），直接显示会露出一串图片地址——
// 本函数据"去表情"的口径把它们一并去掉（真机实测：帖子正文与评论里都会出现该占位）。
export function removeCommunityEmoji(value: string): string {
  return value
    .replace(/\[emoji:[^\]]*\]/g, '')
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '')
    .trim();
}

export function normalizeCommunityText(value: string): string {
  return removeCommunityEmoji(value).replace(/\s+/g, ' ').trim();
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/\n/g, '<br/>');
}

// 发布载荷（对齐 7378 buildCommunityArticlePayload 的 ASL/HTML 结构）
export function buildCommunityArticlePayload(draft: CommunityArticleDraft): string {
  const title: string = normalizeCommunityText(draft.title);
  const body: string = removeCommunityEmoji(draft.body);
  const asl: string = JSON.stringify(['root', {}, ['p', {}, [
    'span', { 'data-type': 'text' },
    ['span', { 'data-type': 'leaf' }, body]
  ]]]);
  const tags: string[] = [];
  for (const t of draft.tags) {
    const n: string = normalizeCommunityText(t);
    if (n.length > 0 && tags.length < 5) {
      tags.push(n);
    }
  }
  const parts: string[] = [];
  parts.push(`"title":${JSON.stringify(title)}`);
  parts.push(`"article_type":${JSON.stringify(draft.articleType)}`);
  parts.push(`"tags":${JSON.stringify(tags)}`);
  parts.push(`"body_asl":${JSON.stringify(asl)}`);
  parts.push('"body_html":' + JSON.stringify(
    `<article class="4ever-article"><p><span data-type="text">${escapeHtml(body)}</span></p></article>`));
  parts.push(`"body_text":${JSON.stringify(body)}`);
  parts.push('"related_skill_ids":[]');
  parts.push('"related_plugin_ids":[]');
  return `{${parts.join(',')}}`;
}

export function communityArticleUrl(articleId: string): string {
  return `${PLATFORM_BASE_URL}/community/articles/${encodeURIComponent(articleId)}`;
}

// ============ API ============

function parseBadge(value: Object): CommunityBadge | null {
  const o: Record<string, Object> | null = objOf(value);
  if (o === null) {
    return null;
  }
  const badge: CommunityBadge = {
    code: strOf(o, 'code', ''),
    label: strOf(o, 'label', ''),
    tier: numOf(o, 'tier', 0),
    badgeKind: strOf(o, 'badge_kind', '')
  };
  return badge;
}

function parseArticle(item: Object): CommunityArticleSummary {
  const o: Record<string, Object> = item as Record<string, Object>;
  const article: CommunityArticleSummary = {
    id: strOf(o, 'id', ''),
    title: strOf(o, 'title', ''),
    summary: strOf(o, 'summary', ''),
    tags: strArrOf(o, 'tags'),
    liked: boolOf(o, 'liked', false),
    favorited: boolOf(o, 'favorited', false),
    articleType: strOf(o, 'article_type', ''),
    articleTypeLabel: strOf(o, 'article_type_label', ''),
    relatedSkillIds: strArrOf(o, 'related_skill_ids'),
    relatedPluginIds: strArrOf(o, 'related_plugin_ids'),
    coverUrl: strOf(o, 'cover_url', ''),
    qaStatus: strOf(o, 'qa_status', ''),
    authorName: strOf(o, 'author_name', ''),
    authorAvatarUrl: strOf(o, 'author_avatar_url', ''),
    identityBadge: parseBadge(o['identity_badge']),
    isFeatured: boolOf(o, 'is_featured', false),
    likeCount: numOf(o, 'like_count', 0),
    favoriteCount: numOf(o, 'favorite_count', 0),
    commentCount: numOf(o, 'comment_count', 0),
    viewCount: numOf(o, 'view_count', 0),
    publishedAt: strOf(o, 'published_at', '')
  };
  return article;
}

function parseComment(item: Object): CommunityComment {
  const o: Record<string, Object> = item as Record<string, Object>;
  const replies: CommunityComment[] = [];
  const raw: Object = o['replies'];
  if (Array.isArray(raw)) {
    for (const r of raw as Object[]) {
      replies.push(parseComment(r));
    }
  }
  const comment: CommunityComment = {
    id: strOf(o, 'id', ''),
    kind: strOf(o, 'kind', 'comment'),
    content: strOf(o, 'content', ''),
    liked: boolOf(o, 'liked', false),
    accepted: boolOf(o, 'accepted', false),
    replies: replies,
    authorName: strOf(o, 'author_name', ''),
    authorAvatarUrl: strOf(o, 'author_avatar_url', ''),
    likeCount: numOf(o, 'like_count', 0),
    createdAt: strOf(o, 'created_at', '')
  };
  return comment;
}

export interface CommunityListOptions {
  page: number;
  pageSize: number;
  sort: string;     // 'recommended' | 'latest'
  type: string;     // 空串 = 全部
}

export async function listCommunityArticles(
  options: CommunityListOptions): Promise<CommunityArticlePage> {
  let path: string = `/api/v1/community/articles?page=${options.page}` +
    `&page_size=${options.pageSize}&sort=${options.sort}`;
  if (options.type.length > 0) {
    path += `&type=${encodeURIComponent(options.type)}`;
  }
  const data: Object = await platformPublicRequest(path);
  const o: Record<string, Object> = objOf(data) !== null
    ? objOf(data) as Record<string, Object> : {};
  const items: CommunityArticleSummary[] = [];
  const raw: Object = o['items'];
  if (Array.isArray(raw)) {
    for (const item of raw as Object[]) {
      items.push(parseArticle(item));
    }
  }
  const page: CommunityArticlePage = {
    items: items,
    total: numOf(o, 'total', items.length),
    page: numOf(o, 'page', options.page),
    pageSize: numOf(o, 'page_size', options.pageSize)
  };
  return page;
}

export async function getCommunityMeta(): Promise<CommunityMeta> {
  const data: Object = await platformPublicRequest('/api/v1/community/meta');
  const o: Record<string, Object> = objOf(data) !== null
    ? objOf(data) as Record<string, Object> : {};
  const meta: CommunityMeta = {
    filterTypes: parseTypes(o['filter_types']),
    fixedTags: parseTypes(o['fixed_tags'])
  };
  return meta;
}

function parseTypes(value: Object): CommunityArticleType[] {
  const out: CommunityArticleType[] = [];
  if (Array.isArray(value)) {
    for (const item of value as Object[]) {
      const o: Record<string, Object> | null = objOf(item);
      if (o !== null) {
        out.push({ code: strOf(o, 'code', ''), label: strOf(o, 'label', '') });
      }
    }
  }
  return out;
}

export async function getCommunityComments(articleId: string): Promise<CommunityCommentPage> {
  const data: Object = await platformPublicRequest(
    `/api/v1/community/articles/${encodeURIComponent(articleId)}/comments?page=1&page_size=50`);
  const o: Record<string, Object> = objOf(data) !== null
    ? objOf(data) as Record<string, Object> : {};
  const items: CommunityComment[] = [];
  const raw: Object = o['items'];
  if (Array.isArray(raw)) {
    for (const item of raw as Object[]) {
      items.push(parseComment(item));
    }
  }
  const page: CommunityCommentPage = { items: items, total: numOf(o, 'total', items.length) };
  return page;
}

export interface CommunityArticleDetail {
  article: CommunityArticleSummary;
  bodyHtml: string;
  bodyText: string;
}

export async function getCommunityArticle(articleId: string): Promise<CommunityArticleDetail> {
  const data: Object = await platformPublicRequest(
    `/api/v1/community/articles/${encodeURIComponent(articleId)}`);
  const o: Record<string, Object> = objOf(data) !== null
    ? objOf(data) as Record<string, Object> : {};
  const detail: CommunityArticleDetail = {
    article: parseArticle(data),
    bodyHtml: strOf(o, 'body_html', ''),
    bodyText: strOf(o, 'body_text', '')
  };
  return detail;
}

export async function likeCommunityArticle(ctx: Context, articleId: string): Promise<CommunityArticleSummary> {
  const data: Object = await platformRequest(ctx,
    `/api/v1/community/articles/${encodeURIComponent(articleId)}/like`, http.RequestMethod.POST, null);
  return parseArticle(data);
}

export async function createCommunityComment(ctx: Context, articleId: string,
  content: string): Promise<CommunityComment> {
  const body: string = JSON.stringify({
    'content': content.trim(), 'parent_id': null, 'kind': 'comment', 'media_ids': []
  });
  const data: Object = await platformRequest(ctx,
    `/api/v1/community/articles/${encodeURIComponent(articleId)}/comments`,
    http.RequestMethod.POST, body);
  return parseComment(data);
}

// 发布：返回新文章 id（7378 发布后跳转到该文章详情）
export async function publishCommunityArticle(ctx: Context, draft: CommunityArticleDraft): Promise<string> {
  const data: Object = await platformRequest(ctx, '/api/v1/community/articles',
    http.RequestMethod.POST, buildCommunityArticlePayload(draft));
  return strOf(data as Record<string, Object>, 'id', '');
}
