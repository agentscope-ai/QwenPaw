---
summary: Drive a live browser with async Python against the builtin Browser SDK
---

Drive a live browser through the builtin **Browser SDK**. The tool accepts a single `code` argument: module-level async Python executed in the caller's session-scoped kernel.

**Parameters**

- `code` — module-level async Python; use `await`, then `return` or `print()` for output

**Typical usage**

```python
browser = await Browser.connect()
page = await browser.open("https://example.com")
obs = await page.snapshot()
print(obs.text)
await page.get_by_role("button", name="Search").click()
obs = await page.snapshot()
print("done")
```

**How it works**

- The SDK is already in scope as `Browser`; connect once, open a page, then loop **perceive → act → verify**
- Session variables such as `browser` and `page` persist across calls; reconnect after a session reset
- For login, captcha, or 2FA, call `await browser.handoff(...)` and stop — never automate those flows

**Notes**

- This is QwenPaw's unified Browser SDK, **not** the legacy `action` / `page_x` / `cdp_port` contract
- Legacy parameters such as `action=` return an error directing callers to use `code=`
- The full API ships with the bound **browser** skill; re-load that skill after context compaction
