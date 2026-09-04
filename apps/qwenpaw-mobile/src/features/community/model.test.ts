import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCommunityArticlePayload,
  communityInitials,
  formatCommunityDate,
  normalizeCommunityText,
} from "./model";

test("creates initials for platform community authors", () => {
  assert.equal(communityInitials("Osier Yi"), "OY");
  assert.equal(communityInitials("平台管理员"), "平台");
  assert.equal(communityInitials(""), "QP");
});

test("formats recent community timestamps", () => {
  const originalNow = Date.now;
  Date.now = () => new Date("2026-08-25T10:00:00Z").getTime();
  assert.equal(formatCommunityDate("2026-08-25T09:52:00Z"), "8 分钟前");
  Date.now = originalNow;
});

test("normalizes whitespace and removes pictographic emoji", () => {
  assert.equal(normalizeCommunityText("一起交流  \n  欢迎\u{1F44B}"), "一起交流 欢迎");
});

test("builds the Platform article payload without sensitive extras", () => {
  const payload = buildCommunityArticlePayload({
    title: "移动端实践",
    articleType: "work_share",
    body: "第一行\n第二行 <safe>",
    tags: ["qwenpaw", "mobile"],
  });
  assert.equal(payload.article_type, "work_share");
  assert.equal(payload.body_text, "第一行\n第二行 <safe>");
  assert.match(payload.body_html, /&lt;safe&gt;/);
  assert.deepEqual(payload.related_skill_ids, []);
});
