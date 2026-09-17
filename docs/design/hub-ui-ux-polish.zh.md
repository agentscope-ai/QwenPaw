# Hub UI/UX 正式改造

用户已将需求从一个联合 skill mock 改为基于当前分支新建分支、直接修改正式前端。分支：`feat/hub-ui-ux-polish`，基于 `6fed35500`。不新增模拟页面或假数据，不改后端 API。

## 设计与规则协调

使用 `frontend-design` 做信息组织，`make-interfaces-feel-better` 做交互与排版打磨。遵循用户偏好的深色主区域、统一橙色和简约专业风格。

- 配色沿用主题变量：主背景、表面、文本、橙色强调、成功与错误语义；深色主区域保持棕色。
- 字体保留现有系统栈，正文 14px、辅助文字至少 12px、主标题 30px；动态数字用 tabular-nums。
- 概览布局：异常处理入口 → 在线率与可筛选的真实状态分布 / 用户与实例入口 → 主机资源 / 最近活动。
- 静态审美与反馈分工：高频导航、列表只改颜色，不播放入场动画；动作按压 0.96，尊重减少动画。
- 使用项目的 Less、Lucide React、Ant Design，不引入另一套 UI 或样式框架。
- 不为了圆角数学强行改变所有层次；相邻嵌套层保持内外间距协调，结构边框和焦点边框保留。
- 生产概览 API 仅提供状态计数，不捏造原型中的实例名称；提供真实计数分布和筛选跳转。

## Checklist

- [x] 创建独立分支，删除本轮未完成 mock 草稿。
- [x] 克隆两套 skill，记录来源、版本及许可位置。
- [x] 改造概览重点层级与状态筛选入口。
- [x] 统一全部 Hub 页面的文字、间距、焦点与触控区域。
- [x] 移动端用 Drawer 保留完整导航、账户和刷新入口。
- [x] 完成刷新反馈与异常提示，保留真实业务操作。
- [x] 通过相关测试、类型检查、格式与静态检查。
- [x] 用独立测试数据验证正式组件桌面、窄屏、深色与交互状态。

## 审查边界

前端正式组件；不更改 API、权限、数据模型、真实用户或运行实例。视觉验证可使用隔离测试夹具，不能把夹具写入生产组件。

## 最终设计（按用户“大重构”要求修订）

本轮替换旧页面外壳与概览结构，而非在旧卡片上追加样式。

- `components/HubShell.tsx`：独立工作空间、重新排序的主导航、轻量状态栏、分层账户区、完整移动端 Drawer。
- `components/OverviewPanel.tsx`：一个运行状态主区域（在线率 + 真实状态比例 + 筛选），右侧组织管理入口，横向主机资源，独立审计活动列表。移除旧的三张等权指标卡和资源区域多余留白。
- 运行环境、凭据、审计：独立筛选区、统一表格与分页表面，主副文本清晰分层。
- 用户：桌面对齐列，小屏采用身份/状态、用量/额度两层信息布局；保留现有详情与权限表单。
- 模型：标题说明、分类导航、默认模型设置、查询过滤、模型目录分层，配置与测试动作维持原有实现。
- 设置：桌面采用侧向分类导航，窄屏改顶部标签；设置区以标题、说明、字段组形成层级。
- 桌面标题 30px，窄屏 27px。语义色沿用项目主题，主区域深棕色；不新增外部字体或装饰图片。

## 联合 skill 自查（full）

范围为上述七个 Hub 主页面及用户弹窗、设置子页。React + Less + Ant Design + Lucide React；现成交互组件负责抽屉、表单和弹窗，CSS 只处理短状态过渡。

| 类别 | 已检查证据 | 结果 |
| --- | --- | --- |
| Typography | 1440 / 1024 / 768 / 390px 截图；标题、数字、表格主副文本 | 统一字号、数字对齐及文字换行 |
| Surfaces | 主状态区、管理入口、列表、设置分组、移动端用户条目 | 修正层级与空间分配，保留结构边界 |
| Animations | hover、focus、按压规则；Drawer 使用 CDP 0.1 倍速打开并中途 Escape 关闭；减少动画媒体偏好 | 高频操作无入场效果；按压 0.96 仅用于主动作；减少动画不执行自定义移动 |
| Icons | 新组件 Lucide 图标、菜单与账户按钮、破坏性图标动作名称 | 使用单一图标库，新增图标操作有可访问名称 |
| Performance | 指定属性过渡，无 transition: all，无预设 will-change；构建检查 | 无额外 UI 依赖，无轮询或新增数据请求 |

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | `console/src/pages/Hub/components/OverviewPanel.tsx:26` | 三张指标卡缺少直接关联，资源区留白过多 | 一个状态操作区、管理入口、横向资源与活动列表 | 让运行状态和操作去向形成清晰主次 |
| HIGH | `console/src/pages/Hub/components/HubShell.tsx:37` | 小屏隐藏账户和刷新入口 | 完整 Drawer 导航、账户区和常驻刷新 | 移动端保持功能可达、焦点可控 |
| MEDIUM | `console/src/pages/Hub/index.module.less:98`、`console/src/pages/Hub/governance/governance.module.less:223` | 多个页面字号、行高与筛选布局不一致 | 独立过滤区、标准化表格、响应式用户条目 | 可读性与操作一致性 |
| MEDIUM | `console/src/pages/Hub/index.module.less:236` | 复杂设置用横向标签与密集卡片 | 桌面侧向分类、内容分区，小屏回到顶部标签 | 减轻配置导航负担 |
| MEDIUM | `console/src/pages/Hub/governance/ManagedModelTable.module.less:30`、`console/src/pages/Hub/governance/OrganizationModels.tsx` | 标题缺少说明，默认模型和目录层级不清 | 明确说明、默认设置区、过滤与目录层次 | 保留业务能力并提高辨识度 |
| MEDIUM | `console/src/pages/Hub/index.tsx:362` | 刷新没有忙碌状态或统一错误处理 | loading、错误提示、可重试 | 状态变化不只依赖动画 |
| MEDIUM | `console/src/pages/Hub/components/OverviewPanel.tsx:26` | 无实例时显示 100%；日期格式未传语言 | 无实例显示破折号；使用当前语言格式化日期 | 避免空状态误导，保证本地化一致 |
| MEDIUM | `console/src/pages/Hub/index.tsx:1066` | 审计筛选缺失治理事件 | 补齐已有翻译支持的模型、预算、邀请等动作 | 活动进入后能继续有效筛选 |
| LOW | `console/src/pages/Hub/components/HubShell.module.less`、`console/src/pages/Hub/components/OverviewPanel.module.less` | 焦点、图标按钮、动作反馈规格不统一 | 可见焦点、命名、触控区域、短颜色过渡 | 提升鼠标、键盘与触控的精细体验 |

### 考虑但未采用

| 位置 | 候选 | 不采用原因 |
| --- | --- | --- |
| 概览 | 用模拟名字画九个实例格 | 生产 API 只提供计数；不伪造实体或为装饰新增请求 |
| 全站 | 大面积入场与卡片浮动 | 后台高频使用，重复动画会打断操作 |
| 字体 | 新增外部商业字体 | 中文覆盖、离线环境与加载成本不匹配；系统栈更可靠 |
| 模型列表 | 每个模型都改成大卡片 | Token 边界、状态、供应商和权限更适合横向比较 |

### 验证边界

- 七个主页面、用户编辑、模型空态、设置安全与运行环境子页已用隔离测试数据检查；无浏览器运行时错误。
- 检查桌面/平板/移动布局、深色模式、可见焦点、hover、加载/空态、减少动画及 Drawer Escape 关闭。
- 真实后台数据写入、Safari / Firefox、完整生产登录流程未验证；未对真实账号、密钥或运行环境执行修改。
- 截图在 `output/hub-ui-polish/`。临时测试入口已清理，项目没有新增 mock 产品页面。


### 最终检查结果

- Hub 页面、工具函数、语言覆盖：46/46 测试通过。
- `npm run build:test` 通过（包含 TypeScript 构建与 Vite 打包）。打包仍提示项目已有的动态/静态混用导入和大 chunk 警告。
- 修改 TSX 文件 ESLint 无错误或警告；Prettier 与 `git diff --check` 通过。
- Verdict：**Approve（本次前端验证范围）**。未验证项：真实后端写入、Safari / Firefox、完整生产登录链路。
