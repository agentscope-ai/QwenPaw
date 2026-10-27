---
summary: 通过异步 Python 调用内置 Browser SDK 驱动真实浏览器
---

通过内置 **Browser SDK** 驱动真实浏览器。工具接受单个 `code` 参数：模块级 async Python，在会话级内核中执行。

**参数**

- `code` — 模块级 async Python；可使用 `await`，通过 `return` 或 `print()` 输出结果

**典型用法**

```python
browser = await Browser.connect()
page = await browser.open("https://example.com")
obs = await page.snapshot()
print(obs.text)
await page.get_by_role("button", name="Search").click()
obs = await page.snapshot()
print("done")
```

**工作方式**

- SDK 已注入为 `Browser`；先 `connect()`，再 `open(url)`，循环 **感知 → 操作 → 验证**
- 会话内变量（`browser`、`page`）会跨调用保留；若会话重置需重新 `connect()`
- 登录、验证码、2FA 等需人工完成的步骤：调用 `await browser.handoff(...)` 后停止

**注意**

- 这是 QwenPaw 内置 Browser SDK，**不是**旧版 `action` / `page_x` / `cdp_port` 接口
- 若传入 legacy 参数（如 `action=`），工具会返回错误并提示改用 `code=`
- 完整 API 参考见绑定 skill **browser**；上下文压缩后请重新加载该 skill
