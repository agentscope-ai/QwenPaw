---
name: news
description: "Look up the latest news for the user from specified news sites. Provides authoritative URLs for politics, finance, society, world, tech, sports, and entertainment. Use browser_use to open each URL and snapshot to get content, then summarize for the user."
metadata:
  {
    "copaw":
      {
        "emoji": "📰",
        "requires": {}
      }
  }
---

# News Reference

When the user asks for "latest news", "what's in the news today", or "news in category X", use the **browser_use** tool with the categories and URLs below: open the page, take a snapshot, then extract headlines and key points from the page content and reply to the user.

## Categories and Sources

| Category      | Source                    | URL |
|---------------|---------------------------|-----|
| **Politics**  | People's Daily · CPC News | https://cpc.people.com.cn/ |
| **Finance**   | China Economic Net        | http://www.ce.cn/ |
| **Society**   | China News · Society      | https://www.chinanews.com/society/ |
| **World**     | CGTN                      | https://www.cgtn.com/ |
| **Tech**      | Science and Technology Daily | https://www.stdaily.com/ |
| **Sports**    | CCTV Sports               | https://sports.cctv.com/ |
| **Entertainment** | Sina Entertainment   | https://ent.sina.com.cn/ |

## How to Use (browser_use)

1. **Clarify the user's need**: Determine which category or categories (politics / finance / society / world / tech / sports / entertainment), or pick 1–2 to fetch.
2. **Pick the URL**: Use the URL from the table for that category; for multiple categories, repeat the steps below for each URL.
3. **Open the page**: Call **browser_use** with:
   ```json
   {"action": "open", "url": "https://www.chinanews.com/society/"}
   ```
   Replace `url` with the corresponding URL from the table.
4. **Take a snapshot**: In the same session, call **browser_use** again:
   ```json
   {"action": "snapshot"}
   ```
   Extract headlines, dates, and summaries from the returned page content.
5. **Summarize the reply**: Organize a short list (headline + one or two sentences + source) by time or importance; if a site is unreachable or times out, say so and suggest another source.

## Notes

- Page structure may change when sites are updated; if extraction fails, say so and suggest the user open the link directly.
- When visiting multiple categories, run `open` for each URL, then `snapshot`, to avoid mixing content from different pages.
- You may include the original link in the reply so the user can open it.
