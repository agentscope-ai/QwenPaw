---
title: 频道页面布局改造设计
date: 2026-06-24
status: draft
author: 赵壮
---

# 频道页面布局改造设计

## 概述

将频道页面从当前的统一网格布局改造为类似模型页面的双区域布局：已激活频道使用大卡片展示，未激活频道使用紧凑的小卡片展示，两个区域分开显示，提升视觉层次和信息密度。

## 背景与动机

### 当前问题
- 所有频道（激活/未激活）混在一起展示，视觉层次不清晰
- 未激活频道占用过多空间，信息密度低
- 用户难以快速识别哪些频道已启用

### 目标
- 参考模型页面的成熟设计模式，实现已激活/未激活频道的分离展示
- 未激活频道使用紧凑的小卡片，提高信息密度
- 保持已激活频道的完整信息展示和交互体验

## 设计决策

### 方案选择

**选定方案：参考模型页面但为频道定制**

- 参考模型页面的布局结构和视觉设计
- 为频道页面创建独立的样式和组件
- 保留频道的业务特性（启用/禁用、访问控制等）

**理由**：
1. 频道和模型的业务逻辑差异较大
2. 在视觉一致性和业务灵活性之间取得最佳平衡
3. 开发成本可控，未来维护更清晰

**备选方案**：
- 方案 A：完全复用模型页面组件（一致性最高，但灵活性差）
- 方案 C：抽取通用组件（长期维护成本低，但初期开发成本高）

## 详细设计

### 1. 整体架构和组件结构

#### 页面布局结构

```
ChannelsPage
├── PageHeader (保持不变)
│   ├── 面包屑导航
│   ├── 筛选标签 (全部/内置/自定义)
│   └── 操作按钮 (待审批、访问控制)
│
└── channelsContainer (可滚动区域)
    ├── 已激活区域 (Enabled Section)
    │   ├── 区域标题：🟢 已激活 + 数量统计
    │   └── channelsGrid (大卡片网格，保持现有样式)
    │       └── ChannelCard (现有组件，不变)
    │
    └── 未激活区域 (Available Section)
        ├── 区域标题：⚪ 未激活
        └── availableGrid (小卡片网格，新样式)
            └── ChannelAvailableItem (新组件)
                ├── 频道图标
                ├── 频道名称
                └── "启用"按钮
```

#### 新增/修改的组件

1. **修改 `ChannelsPage`**：
   - 将 `cards` 数据拆分为 `enabledCards` 和 `disabledCards`
   - 渲染两个独立的区域

2. **新增 `ChannelAvailableItem` 组件**：
   - 小卡片样式，参考模型页面的 `availableItem`
   - 点击后打开 ChannelDrawer 进行配置

3. **修改样式文件**：
   - 新增 `panelSection`、`panelTitle`、`availableGrid`、`availableItem` 等样式类
   - 参考模型页面的视觉设计

### 2. 数据流、交互和错误处理

#### 数据流

1. **数据获取**：保持现有的 `useChannels` hook 不变
2. **数据拆分**：在 `ChannelsPage` 组件中，将 `cards` 拆分为：
   - `enabledCards`：`config.enabled === true` 的频道
   - `disabledCards`：`config.enabled === false` 的频道
3. **筛选逻辑**：现有的 `filter`（全部/内置/自定义）同时应用于两个区域

#### 交互行为

**已激活区域（大卡片）**：
- 点击卡片 → 打开 `ChannelDrawer` 编辑配置（保持现有行为）

**未激活区域（小卡片）**：
- 点击小卡片 → 打开 `ChannelDrawer` 进行初始配置
- Drawer 打开时，`enabled` 字段默认为 `false`，用户需要手动启用
- 保存后自动刷新数据，频道会移动到已激活区域

#### 空状态处理

- **已激活区域为空**：显示提示文案 "暂无已激活频道" + 引导按钮 "去启用频道"（滚动到未激活区域）
- **未激活区域为空**：不显示该区域（所有频道都已激活）

#### 错误处理

- 数据加载失败：保持现有的 loading 和 error 状态展示
- 保存配置失败：保持现有的 `message.error` 提示

### 3. 视觉样式和响应式设计

#### 已激活区域样式

参考模型页面的 `panelSection`：
- **容器**：实线边框，浅色背景，圆角 12px
- **标题**：绿色圆点 + "已激活" + 数量统计（如 "已激活 3 个"）
- **卡片网格**：保持现有的 `channelsGrid` 样式（`grid-template-columns: repeat(auto-fill, minmax(346px, 1fr))`）

#### 未激活区域样式

参考模型页面的 `panelSectionDashed` 和 `availableGrid`：
- **容器**：虚线边框，透明背景，圆角 12px
- **标题**：灰色圆点 + "未激活"
- **小卡片网格**：`grid-template-columns: repeat(auto-fill, minmax(200px, 1fr))`
- **小卡片样式**（`availableItem`）：
  - 高度约 48px，水平排列
  - 左侧：频道图标（24px）+ 频道名称
  - 右侧："启用"文字链接
  - 悬停效果：背景色变化，文字颜色加深

#### 响应式设计

**桌面端（>768px）**：
- 已激活区域：大卡片网格，每行 2-3 个
- 未激活区域：小卡片网格，每行 4-6 个

**移动端（≤768px）**：
- 已激活区域：大卡片单列
- 未激活区域：小卡片单列
- 区域标题和容器 padding 适当缩小

#### 暗色模式

参考模型页面的暗色模式样式：
- 容器背景：`rgba(255, 255, 255, 0.03)`
- 边框颜色：`rgba(255, 255, 255, 0.06)`（实线）/ `rgba(255, 255, 255, 0.1)`（虚线）
- 文字颜色：`rgba(255, 255, 255, 0.85)`（标题）/ `rgba(255, 255, 255, 0.5)`（副标题）

## 技术实现要点

### 文件变更清单

1. **修改文件**：
   - `console/src/pages/Control/Channels/index.tsx`
   - `console/src/pages/Control/Channels/index.module.less`

2. **新增文件**：
   - `console/src/pages/Control/Channels/components/ChannelAvailableItem.tsx`

3. **更新导出**：
   - `console/src/pages/Control/Channels/components/index.ts`

### 关键实现细节

1. **数据拆分逻辑**：
   ```typescript
   const enabledCards = cards.filter(({ config }) => config.enabled);
   const disabledCards = cards.filter(({ config }) => !config.enabled);
   ```

2. **小卡片组件**：
   - 使用 `ChannelIcon` 组件显示图标
   - 点击事件调用 `handleCardClick` 打开 Drawer

3. **样式复用**：
   - 参考 `console/src/pages/Settings/Models/index.module.less` 中的相关样式类
   - 为频道页面创建独立的样式定义

## 测试计划

### 功能测试
- [ ] 已激活频道正确显示在大卡片区域
- [ ] 未激活频道正确显示在小卡片区域
- [ ] 筛选功能（全部/内置/自定义）对两个区域都生效
- [ ] 点击大卡片打开 Drawer 编辑配置
- [ ] 点击小卡片打开 Drawer 进行初始配置
- [ ] 保存配置后频道正确移动到对应区域

### 视觉测试
- [ ] 桌面端布局正确（大卡片网格 + 小卡片网格）
- [ ] 移动端布局正确（单列显示）
- [ ] 暗色模式样式正确
- [ ] 空状态显示正确

### 边界情况
- [ ] 所有频道都已激活（不显示未激活区域）
- [ ] 所有频道都未激活（显示空状态提示）
- [ ] 筛选后某个区域为空

## 后续工作

1. 实现完成后进行视觉走查，确保与模型页面风格一致
2. 收集用户反馈，根据实际使用情况优化交互细节
3. 考虑是否需要为其他页面（如插件管理）应用类似的布局模式
