# QwenPaw 官方主题配置

## 1. 状态与范围

- 状态：实现完成，自动化验证通过
- 关联 Issue：`agentscope-ai/QwenPaw#7406`
- 范围：根 `config.json`、主题配置 API、Console 主题运行时、通用设置页
- 不包含：字体配置、全局间距密度、逐个迁移历史硬编码圆角、插件私有样式

主题仅控制颜色与圆角，不修改 Console 原有字体。Issue 正文没有定义全局间距
的取值或语义，当前 Console 也没有统一的间距 token，因此本期不引入无法稳定
落地的密度配置。

## 2. 配置契约

根 `config.json` 可选地包含稀疏 `theme` 对象：

```json
{
  "theme": {
    "accent": "#0b57d0",
    "accent_hover": "#1967d2",
    "accent_bg": "rgba(11, 87, 208, 0.1)",
    "radius": "12px",
    "dark": {
      "accent": "#8ab4f8",
      "accent_bg": "rgba(138, 180, 248, 0.15)",
      "surface": "#1a1a1a"
    }
  }
}
```

所有字段均可省略。没有 `theme`、删除主题或字段为空时继续使用当前内置值，
不会把默认主题物化到配置文件。颜色字段接受十六进制及 `rgb`/`rgba`/`hsl`/
`hsla`，圆角接受 `0` 或像素值。

## 3. API

- `GET /api/config/theme`：返回稀疏主题配置，未配置时返回 `{}`。
- `PUT /api/config/theme`：校验并原子替换主题配置。
- `DELETE /api/config/theme`：删除自定义主题并恢复内置默认值。

配置读写复用根配置事务，通过异步线程包装执行，避免同步文件 IO 阻塞事件
循环。主题只影响 UI，不触发 Agent 重载。

## 4. Console 应用规则

主题运行时在后端可用后加载配置，并同时更新：

1. Ant Design 的主色和基础圆角 token；
2. `--app-accent*`、`--app-surface`、`--app-radius` 等项目语义变量；
3. 兼容现有组件的 `--border-radius` 别名。

深色模式优先使用 `theme.dark` 中的覆盖值，缺失字段回退到通用主题，再回退
到内置主题。设置页编辑时即时预览，只有点击保存才写入配置；保存失败恢复
已持久化主题。恢复默认会删除配置。

设置页提供 QwenPaw、Codex、Ayu、Catppuccin、Dracula 和 Everforest 六套
主题配色。下拉选项使用 `Aa` 色样展示强调色与深色表面的组合；选择预设会
即时预览颜色，并保留当前圆角。手工调整颜色后显示为自定义主题。

## 5. 验收 Checklist

- [x] 明确 Issue 范围、默认行为和非目标
- [x] 增加主题配置模型、校验和稀疏持久化
- [x] 增加主题 GET、PUT、DELETE API
- [x] 增加后端模型与路由单测
- [x] 增加前端主题 API 与运行时映射
- [x] 在通用设置页增加六套主题配色、颜色、圆角、保存和恢复默认控件
- [x] 保持 Console 原有字体，不允许主题配置修改字体
- [x] 补齐全部 Console 语言文案
- [x] 增加前端主题与交互单测
- [x] 通过后端测试
- [ ] Python pre-commit（当前 Conda 环境未安装 pre-commit）
- [x] 通过前端 TypeScript 检查与全量测试（356 files / 3504 tests）
- [ ] 前端全仓 lint（现有仓库已有 306 个错误，未由本改动引入）
- [ ] 生产构建（需在清理既有生成物后执行）
- [x] 完成浏览器浅色主题与配色下拉视觉验证
- [ ] 完成浏览器深色及响应式视觉验证
