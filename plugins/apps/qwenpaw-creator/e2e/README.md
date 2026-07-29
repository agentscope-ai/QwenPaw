# Creator Timeline/Element E2E

这套浏览器验收只覆盖当前文件原生架构：

- `project.json` 是创作数据的唯一持久化权威，`schema_version` 固定为 `2`。
- 每个 Project 只有一个主 Timeline；可重叠内容直接存放在
  `timelines.items[timelineId].elements_by_id`。
- Plan 页面同时验证纵向 Element 列表、局部时间线、重叠 Element 选择和
  与项目画面比例一致的大尺寸成片预览。
- 素材验收直接检查 Project Asset Index，不依赖额外的 View 投影。

先启动 Creator backend 与 Vite UI，再执行：

```bash
cd plugins/apps/qwenpaw-creator/e2e
pytest
```

默认服务地址为 `http://127.0.0.1:5173`，可用
`CREATOR_E2E_BASE_URL` 覆盖。设置 `CREATOR_E2E_STRICT=1` 后，服务未启动会
直接失败；否则测试会跳过。
