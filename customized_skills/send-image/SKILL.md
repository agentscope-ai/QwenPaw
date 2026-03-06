---
name: send-image
description: 向用户的 Telegram 或 Discord 发送图片。用于截图分享、表情包、文件预览等场景。CC 在对话中需要发图片时调用此 skill。
version: "1.0.0"
---

# Send Image — 跨通道图片发送

CC 需要给用户发图片时使用。支持本地文件和网络 URL。

## 使用场景

1. **截图分享**：浏览器截图、桌面截图后发给用户查看
2. **表情包**：搜索到有趣的表情包图片 URL，发送给用户
3. **文件预览**：工具界面、文档截图等，让用户直观了解

## 使用方法

### 发送本地图片（截图等）
```bash
python "C:\Users\giwan.CGG\.copaw\customized_skills\send-image\scripts\send_image.py" "C:\path\to\screenshot.png"
```

### 发送本地图片 + 说明文字
```bash
python "C:\Users\giwan.CGG\.copaw\customized_skills\send-image\scripts\send_image.py" "C:\path\to\image.png" --caption "这是首页截图"
```

### 发送网络图片 URL
```bash
python "C:\Users\giwan.CGG\.copaw\customized_skills\send-image\scripts\send_image.py" "https://example.com/image.png"
```

### 指定通道（默认自动识别当前通道）
```bash
python "C:\Users\giwan.CGG\.copaw\customized_skills\send-image\scripts\send_image.py" "image.png" --channel telegram
python "C:\Users\giwan.CGG\.copaw\customized_skills\send-image\scripts\send_image.py" "image.png" --channel discord
```

## 通道自动选择逻辑

- 读取 `config.json` 的 `last_dispatch.channel` 判断当前通道
- 如果当前通道是 console，优先尝试 telegram，其次 discord
- 可通过 `--channel` 手动指定

## ⚠️ 注意事项

- 图片不包含敏感信息（密码、token 等）
- TG 图片大小限制 10MB，DC 限制 25MB
- 网络不通时静默失败，不阻塞主任务
- 纯 Python 标准库，无额外依赖
