---
name: news
description: "为用户从指定新闻网站查找最新新闻。提供政治、财经、社会、国际、科技、体育和娱乐类别的权威 URL。使用 browser_use 打开每个 URL 并通过 snapshot 获取内容，然后为用户总结。"
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "📰"
    requires: {}
---

# 新闻参考

当用户询问"最新新闻"、"今天有什么新闻"或"某某类别的新闻"时，使用 **browser_use** 工具配合以下类别和 URL：打开页面，截取快照，然后从页面内容中提取标题和要点并回复用户。

## 类别和来源

| 类别      | 来源                    | URL |
|-----------|--------------------------|-----|
| **政治**  | 人民网 · 中国共产党新闻网 | https://cpc.people.com.cn/ |
| **财经**  | 中国经济网               | http://www.ce.cn/ |
| **社会**  | 中新网 · 社会            | https://www.chinanews.com/society/ |
| **国际**  | CGTN                     | https://www.cgtn.com/ |
| **科技**  | 科技日报                 | https://www.stdaily.com/ |
| **体育**  | 央视体育                 | https://sports.cctv.com/ |
| **娱乐**  | 新浪娱乐                 | https://ent.sina.com.cn/ |

## 使用方法（browser_use）

1. **明确用户需求**：确定用户需要哪个或哪些类别（政治 / 财经 / 社会 / 国际 / 科技 / 体育 / 娱乐），或选择 1-2 个进行获取。
2. **选择 URL**：使用表格中对应类别的 URL；如需多个类别，对每个 URL 重复以下步骤。
3. **打开页面**：调用 **browser_use**：
   ```json
   {"action": "open", "url": "https://www.chinanews.com/society/"}
   ```
   将 `url` 替换为表格中对应的 URL。
4. **截取快照**：在同一会话中，再次调用 **browser_use**：
   ```json
   {"action": "snapshot"}
   ```
   从返回的页面内容中提取标题、日期和摘要。
5. **总结回复**：按时间或重要性组织一个简短列表（标题 + 一两句话 + 来源）；如果网站无法访问或超时，请说明并建议其他来源。

## 注意事项

- 网站更新时页面结构可能会变化；如果提取失败，请说明并建议用户直接打开链接。
- 访问多个类别时，对每个 URL 分别执行 `open` 和 `snapshot`，避免混淆不同页面的内容。
- 可以在回复中包含原始链接，方便用户打开查看。
