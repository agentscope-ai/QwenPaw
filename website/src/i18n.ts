export type Lang = "zh" | "en";

export const i18n: Record<Lang, Record<string, string>> = {
  zh: {
    "nav.docs": "文档",
    "nav.github": "GitHub",
    "nav.githubComingSoon": "Coming Soon",
    "nav.lang": "EN",
    "nav.agentscopeTeam": "AgentScope",
    "hero.slogan": "懂你所需，伴你左右",
    "hero.sub":
      "你的AI个人助理；安装极简、本地与云上均可部署；支持多端接入、能力轻松扩展。",
    "hero.cta": "查看文档",
    "brandstory.title": "Why CoPaw？",
    "brandstory.para1":
      "CoPaw 既是「你的搭档小爪子」（co-paw），也寓意 Co Personal Agent Workstation（协同个人智能体工作台）。",
    "brandstory.para2":
      "我们希望它不是冰冷的工具，而是一只随时准备帮忙的温暖「小爪子」，是你数字生活中最默契的伙伴。",
    "features.title": "核心能力",
    "features.channels.title": "全域触达",
    "features.channels.desc":
      "支持钉钉、飞书、QQ、Discord、iMessage 等频道，一个 CoPaw 按需连接。",
    "features.private.title": "由你掌控",
    "features.private.desc":
      "记忆与个性化由你掌控，本地或云端均可；定时与协作发往指定频道。",
    "features.skills.title": "Skills 扩展",
    "features.skills.desc": "内置定时任务，自定义技能目录，CoPaw 自动加载。",
    "testimonials.title": "社区怎么说",
    "testimonials.viewAll": "查看全部",
    "testimonials.1": "CoPaw 就该这样：多频道一个入口，Python 好改好部署。",
    "testimonials.2": "定时和心跳很实用，Skills 自己加，数据都在本地。",
    "testimonials.3": "想完全掌控的团队用着很顺手。",
    "usecases.title": "你可以用 CoPaw 做什么",
    "usecases.sub": "",
    "usecases.category.social": "社交媒体",
    "usecases.category.creative": "创意与构建",
    "usecases.category.productivity": "生产力",
    "usecases.category.research": "研究与学习",
    "usecases.category.assistant": "桌面与文件",
    "usecases.category.explore": "探索更多",
    "usecases.social.1":
      "每日将小红书、知乎、Reddit 上你关注的热帖整理成摘要并推送，并根据反馈优化推荐。",
    "usecases.social.2":
      "每日抓取 B 站、YouTube 关注频道或关键词下的新视频并生成摘要，节省浏览时间。",
    "usecases.social.3":
      "分析小红书、知乎等账号的内容规律与特点，为内容创作提供参考。",
    "usecases.creative.1":
      "睡前向 CoPaw 说明目标并设定自动执行，次日即可获得可用的雏形。",
    "usecases.creative.2":
      "从选题、找素材到确定方向，CoPaw 可协助完成视频内容创作全流程。",
    "usecases.productivity.1":
      "每日汇总订阅邮件与 Newsletter 精华，并推送至钉钉、飞书或 QQ 会话。",
    "usecases.productivity.2":
      "从邮件与日历自动整理联系人，支持用自然语言查询联系人及往来记录。",
    "usecases.productivity.3":
      "记录饮食与身体反应，由 CoPaw 定期分析并呈现规律。",
    "usecases.research.1":
      "自动追踪科技与 AI 公司财报与重要资讯，筛选重点并生成摘要。",
    "usecases.research.2":
      "将链接、文章与帖子存入个人知识库，便于在多场景中检索与复用。",
    "usecases.assistant.1":
      "协助整理与搜索本地文件、阅读文档并做摘要；在钉钉、飞书或 QQ 中通过对话将指定文件发至当前会话。",
    "usecases.explore.1":
      "你可以探索更多可能，用 Skills 与定时任务组合成 agentic app。",
    "quickstart.title": "快速开始",
    "quickstart.hintBefore": "安装 → 初始化 → 启动；频道配置见 ",
    "quickstart.hintLink": "文档",
    "quickstart.hintAfter": "，即可通过钉钉、飞书、QQ 等频道使用 CoPaw。",
    "quickstart.optionLocal": "一键安装（会创建虚拟环境再安装）",
    "quickstart.optionPip": "pip 安装",
    "quickstart.tabPip": "pip 安装 (推荐)",
    "quickstart.tabPipMain": "pip 安装",
    "quickstart.tabPipSub": "(推荐)",
    "quickstart.tabUnix": "macOS / Linux (Beta)",
    "quickstart.tabUnixMain": "macOS / Linux",
    "quickstart.tabUnixSub": "(Beta)",
    "quickstart.tabWindows": "Windows (Beta)",
    "quickstart.tabWindowsMain": "Windows",
    "quickstart.tabWindowsSub": "(Beta)",
    footer: "CoPaw — 懂你所需，伴你左右",
    "footer.poweredBy.p1": "由 ",
    "footer.poweredBy.p2": " 基于 ",
    "footer.poweredBy.p3": "、",
    "footer.poweredBy.p3b": " 与 ",
    "footer.poweredBy.p4": " 打造。",
    "footer.poweredBy.team": "AgentScope 团队",
    "footer.poweredBy.agentscope": "AgentScope",
    "footer.poweredBy.runtime": "AgentScope Runtime",
    "footer.poweredBy.reme": "ReMe",
    "footer.inspiredBy": "部分灵感来源于 ",
    "footer.inspiredBy.name": "OpenClaw",
    "footer.thanksSkills": "感谢 ",
    "footer.thanksSkills.name": "anthropics/skills",
    "footer.thanksSkills.suffix": " 提供 Agent Skills 规范与示例。",
    "docs.backToTop": "返回顶部",
    "docs.copy": "复制",
    "docs.copied": "已复制",
    "docs.searchPlaceholder": "搜索文档",
    "docs.searchLoading": "加载中…",
    "docs.searchNoResults": "无结果",
    "docs.searchResultsTitle": "搜索结果",
    "docs.searchResultsTitleEmpty": "搜索文档",
    "docs.searchHint": "在左侧输入关键词后按回车搜索。",
  },
  en: {
    "nav.docs": "Docs",
    "nav.github": "GitHub",
    "nav.githubComingSoon": "Coming Soon",
    "nav.lang": "中文",
    "nav.agentscopeTeam": "AgentScope",
    "hero.slogan": "Works for you, grows with you",
    "hero.sub":
      "Your Personal AI Assistant; easy to install, deploy on your own machine or on the cloud; supports multiple chat apps with easily extensible capabilities.",
    "hero.cta": "Read the docs",
    "brandstory.title": "Why CoPaw?",
    "brandstory.para1":
      'CoPaw represents both a Co Personal Agent Workstation and a "co-paw"—a partner always by your side.',
    "brandstory.para2":
      'More than just a cold tool, CoPaw is a warm "little paw" always ready to lend a hand (or a paw!). It is the ultimate teammate for your digital life.',
    "features.title": "Key capabilities",
    "features.channels.title": "Every channel",
    "features.channels.desc":
      "DingTalk, Feishu, QQ, Discord, iMessage, and more — one assistant, connect as you need.",
    "features.private.title": "Under your control",
    "features.private.desc":
      "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",
    "features.skills.title": "Skills",
    "features.skills.desc":
      "Built-in Cron; custom skills in your workspace, auto-loaded.",
    "testimonials.title": "What people say",
    "testimonials.viewAll": "View all",
    "testimonials.1":
      "This is what a personal assistant should be: one entry, every channel.",
    "testimonials.2":
      "Cron and heartbeat are super practical. Add your own skills; data stays local.",
    "testimonials.3": "Teams who want full control love it.",
    "usecases.title": "What you can do with CoPaw",
    "usecases.sub": "",
    "usecases.category.social": "Social media",
    "usecases.category.creative": "Creative & building",
    "usecases.category.productivity": "Productivity",
    "usecases.category.research": "Research & learning",
    "usecases.category.assistant": "Desktop & files",
    "usecases.category.explore": "Explore more",
    "usecases.social.1":
      "Daily digest of hot posts from Xiaohongshu, Zhihu, and Reddit based on your interests, with recommendations that improve over time.",
    "usecases.social.2":
      "Daily summaries of new videos from Bilibili or YouTube by channel or keyword, saving you time browsing.",
    "usecases.social.3":
      "Analyze your Xiaohongshu or Zhihu account to uncover content patterns and inform what to post next.",
    "usecases.creative.1":
      "Describe your goal to CoPaw and set it to run overnight; get a working draft by the next day.",
    "usecases.creative.2":
      "From topic selection and material gathering to direction setting, CoPaw supports the full video content workflow.",
    "usecases.productivity.1":
      "Daily digests of newsletters and important emails, delivered to your DingTalk, Feishu or QQ chat.",
    "usecases.productivity.2":
      "Contacts surfaced from email and calendar, with natural-language search for people and past interactions.",
    "usecases.productivity.3":
      "Log diet and symptoms; CoPaw analyzes and surfaces patterns over time.",
    "usecases.research.1":
      "Track tech and AI company earnings and news; get key points and summaries automatically.",
    "usecases.research.2":
      "Save links, articles, and posts to a personal knowledge base and reuse them across workflows.",
    "usecases.assistant.1":
      "Organize and search local files, read and summarize documents; request files in DingTalk, Feishu or QQ and receive them in the current chat.",
    "usecases.explore.1":
      "Explore more possibilities—combine Skills and cron into your own agentic app.",
    "quickstart.title": "Quick start",
    "quickstart.hintBefore":
      "Install → init → start. Configure channels to use CoPaw on DingTalk, Feishu, QQ, etc. See ",
    "quickstart.hintLink": "docs",
    "quickstart.hintAfter": ".",
    "quickstart.optionLocal":
      "One-click install (creates a virtual env, then installs)",
    "quickstart.optionPip": "pip install",
    "quickstart.tabPip": "pip install (recommended)",
    "quickstart.tabPipMain": "pip install",
    "quickstart.tabPipSub": "(recommended)",
    "quickstart.tabUnix": "macOS / Linux (Beta)",
    "quickstart.tabUnixMain": "macOS / Linux",
    "quickstart.tabUnixSub": "(Beta)",
    "quickstart.tabWindows": "Windows (Beta)",
    "quickstart.tabWindowsMain": "Windows",
    "quickstart.tabWindowsSub": "(Beta)",
    footer: "CoPaw — Works for you, grows with you",
    "footer.poweredBy.p1": "Built by ",
    "footer.poweredBy.p2": " with ",
    "footer.poweredBy.p3": ", ",
    "footer.poweredBy.p3b": ", and ",
    "footer.poweredBy.p4": ".",
    "footer.poweredBy.team": "AgentScope team",
    "footer.poweredBy.agentscope": "AgentScope",
    "footer.poweredBy.runtime": "AgentScope Runtime",
    "footer.poweredBy.reme": "ReMe",
    "footer.inspiredBy": "Partly inspired by ",
    "footer.inspiredBy.name": "OpenClaw",
    "footer.thanksSkills": "Thanks to ",
    "footer.thanksSkills.name": "anthropics/skills",
    "footer.thanksSkills.suffix": " for the Agent Skills spec and examples.",
    "docs.backToTop": "Back to top",
    "docs.copy": "Copy",
    "docs.copied": "Copied",
    "docs.searchPlaceholder": "Search docs",
    "docs.searchLoading": "Loading…",
    "docs.searchNoResults": "No results",
    "docs.searchResultsTitle": "Search results",
    "docs.searchResultsTitleEmpty": "Search docs",
    "docs.searchHint": "Enter a keyword and press Enter to search.",
  },
};

export function t(lang: Lang, key: string): string {
  return i18n[lang][key] ?? key;
}
