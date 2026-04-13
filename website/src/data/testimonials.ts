/**
 * Testimonials (community voices) data.
 * REAL_TESTIMONIALS: production-only; section is hidden when empty in build.
 * MOCK_TESTIMONIALS: dev-only; shown together with real in dev mode.
 */
export interface TestimonialItem {
  avatar: string;
  quoteEn: string;
  quoteZh: string;
  username: string;
  url: string;
}

/** Real community testimonials. Section hidden in build when this is empty. */
export const REAL_TESTIMONIALS: TestimonialItem[] = [];

/** Mock data for dev: shown only in dev together with REAL_TESTIMONIALS. */
export const MOCK_TESTIMONIALS: TestimonialItem[] = [
  {
    avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=alex",
    quoteEn:
      "I've enjoyed my QwenPaw assistant so much. One entry for iMessage, " +
      "Discord, Feishu and DingTalk. It just works.",
    quoteZh: "一个入口管 iMessage、Discord、飞书、钉钉，用下来很顺手。",
    username: "@jdrhyne",
    url: "https://x.com/iamsubhrajyoti/status/2009949389884920153",
  },
  {
    avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=brooke",
    quoteEn:
      "Cron and heartbeat are super practical. Add my own skills; " +
      "data stays local. Exactly what I wanted.",
    quoteZh: "定时和心跳很实用，自己加 Skills，数据都在本地，很放心。",
    username: "@dajaset",
    url: "https://x.com/iamsubhrajyoti/status/2009949389884920153",
  },
  {
    avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=casey",
    quoteEn:
      "Teams who want full control love it. Python + AgentScope, " +
      "everything in our repo.",
    quoteZh: "想完全掌控的团队用着很顺手，Python + AgentScope 全在自家仓库。",
    username: "@Ashwinreads",
    url: "https://x.com/iamsubhrajyoti/status/2009949389884920153",
  },
  {
    avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=drew",
    quoteEn:
      "Personal assistant the way it should be: one entry, every " +
      "channel. No gateway lock-in.",
    quoteZh: "个人助理就该这样：多频道一个入口，没有网关绑架。",
    username: "@KrauseFx",
    url: "https://x.com/iamsubhrajyoti/status/2009949389884920153",
  },
  {
    avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=emery",
    quoteEn:
      "Setup was install, init, start. Docs are clear. Replaced my " +
      "old bot in an afternoon.",
    quoteZh: "安装、初始化、启动，文档清楚，一下午就把原来的 bot 换掉了。",
    username: "@steipete",
    url: "https://x.com/iamsubhrajyoti/status/2009949389884920153",
  },
];
