import type {
  CommunityArticleDraft,
  CommunityArticlePayload,
} from "./types";

export function communityInitials(name: string): string {
  const normalized = name.trim();
  if (!normalized) return "QP";
  const words = normalized.split(/\s+/).filter(Boolean);
  if (words.length > 1) {
    return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
  }
  return Array.from(normalized).slice(0, 2).join("").toUpperCase();
}

export function formatCommunityDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const elapsed = Date.now() - date.getTime();
  if (elapsed >= 0 && elapsed < 60_000) return "刚刚";
  if (elapsed >= 0 && elapsed < 3_600_000) {
    return `${Math.floor(elapsed / 60_000)} 分钟前`;
  }
  if (elapsed >= 0 && elapsed < 86_400_000) {
    return `${Math.floor(elapsed / 3_600_000)} 小时前`;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(date);
}

export function normalizeCommunityText(value: string): string {
  return removeCommunityEmoji(value)
    .replace(/\s+/g, " ")
    .trim();
}

export function removeCommunityEmoji(value: string): string {
  return value
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, "")
    .trim();
}

export function buildCommunityArticlePayload(
  draft: CommunityArticleDraft,
): CommunityArticlePayload {
  const title = normalizeCommunityText(draft.title);
  const body = removeCommunityEmoji(draft.body).trim();
  const asl = [
    "root",
    {},
    [
      "p",
      {},
      [
        "span",
        { "data-type": "text" },
        ["span", { "data-type": "leaf" }, body],
      ],
    ],
  ];
  return {
    title,
    article_type: draft.articleType,
    tags: draft.tags
      .map(normalizeCommunityText)
      .filter(Boolean)
      .slice(0, 5),
    body_asl: JSON.stringify(asl),
    body_html: `<article class="4ever-article"><p><span data-type="text">${escapeHtml(body)}</span></p></article>`,
    body_text: body,
    related_skill_ids: [],
    related_plugin_ids: [],
  };
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/\n/g, "<br/>");
}
