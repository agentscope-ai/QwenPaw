# 频道页面布局改造实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将频道页面改造为双区域布局，已激活频道使用大卡片，未激活频道使用紧凑小卡片

**Architecture:** 参考模型页面的布局模式，在 ChannelsPage 中拆分数据为已激活/未激活两组，分别渲染到独立区域。新增 ChannelAvailableItem 组件用于未激活频道的小卡片展示。

**Tech Stack:** React, TypeScript, Less Modules, Ant Design

---

## 文件结构

### 需要修改的文件
- `console/src/pages/Control/Channels/index.tsx` - 主页面组件，拆分数据并渲染两个区域
- `console/src/pages/Control/Channels/index.module.less` - 页面样式，添加区域容器和小卡片样式
- `console/src/pages/Control/Channels/components/index.ts` - 组件导出，添加新组件

### 需要创建的文件
- `console/src/pages/Control/Channels/components/ChannelAvailableItem.tsx` - 未激活频道小卡片组件

---

## Task 1: 创建 ChannelAvailableItem 组件

**Files:**
- Create: `console/src/pages/Control/Channels/components/ChannelAvailableItem.tsx`

- [ ] **Step 1: 创建组件文件**

```typescript
import React from "react";
import { ChannelIcon } from "./ChannelIcon";
import { getChannelLabel, type ChannelKey } from "./constants";
import styles from "../index.module.less";

interface ChannelAvailableItemProps {
  channelKey: ChannelKey;
  onClick: () => void;
}

export const ChannelAvailableItem = React.memo(function ChannelAvailableItem({
  channelKey,
  onClick,
}: ChannelAvailableItemProps) {
  const { t } = useTranslation();
  const label = getChannelLabel(channelKey, t);

  return (
    <div className={styles.availableItem} onClick={onClick}>
      <ChannelIcon channelKey={channelKey} size={24} />
      <span className={styles.availableItemName}>{label}</span>
      <span className={styles.availableItemAction}>
        {t("channels.enableAction")}
      </span>
    </div>
  );
});
```

- [ ] **Step 2: 添加必要的导入**

在文件顶部添加 `useTranslation` 导入：

```typescript
import { useTranslation } from "react-i18next";
```

- [ ] **Step 3: 提交代码**

```bash
git add console/src/pages/Control/Channels/components/ChannelAvailableItem.tsx
git commit -m "feat(channels): add ChannelAvailableItem component for disabled channels"
```

---

## Task 2: 更新组件导出

**Files:**
- Modify: `console/src/pages/Control/Channels/components/index.ts`

- [ ] **Step 1: 添加新组件导出**

在 `console/src/pages/Control/Channels/components/index.ts` 中添加：

```typescript
export { ChannelAvailableItem } from "./ChannelAvailableItem";
```

- [ ] **Step 2: 提交代码**

```bash
git add console/src/pages/Control/Channels/components/index.ts
git commit -m "feat(channels): export ChannelAvailableItem component"
```

---

## Task 3: 添加国际化文案

**Files:**
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

- [ ] **Step 1: 添加中文文案**

在 `console/src/locales/zh.json` 的 `channels` 对象中添加：

```json
{
  "channels": {
    "enabledSection": "已激活",
    "enabledCount": "{{count}} 个",
    "availableSection": "未激活",
    "enableAction": "启用",
    "noEnabledChannels": "暂无已激活频道",
    "goEnableChannels": "去启用频道"
  }
}
```

- [ ] **Step 2: 添加英文文案**

在 `console/src/locales/en.json` 的 `channels` 对象中添加：

```json
{
  "channels": {
    "enabledSection": "Enabled",
    "enabledCount": "{{count}}",
    "availableSection": "Available",
    "enableAction": "Enable",
    "noEnabledChannels": "No enabled channels",
    "goEnableChannels": "Enable channels"
  }
}
```

- [ ] **Step 3: 提交代码**

```bash
git add console/src/locales/zh.json console/src/locales/en.json
git commit -m "feat(i18n): add channel layout i18n keys"
```

---

## Task 4: 修改 ChannelsPage 数据拆分逻辑

**Files:**
- Modify: `console/src/pages/Control/Channels/index.tsx:48-68`

- [ ] **Step 1: 修改 cards 计算逻辑**

将现有的 `cards` useMemo 替换为分别计算 `enabledCards` 和 `disabledCards`：

```typescript
// Sort cards: enabled first, then disabled (preserve orderedKeys order within each group)
const { enabledCards, disabledCards } = useMemo(() => {
  const enabledCards: { key: ChannelKey; config: Record<string, unknown> }[] =
    [];
  const disabledCards: {
    key: ChannelKey;
    config: Record<string, unknown>;
  }[] = [];

  orderedKeys.forEach((key) => {
    const config = channels[key] || { enabled: false, bot_prefix: "" };
    const builtin = isBuiltin(key);
    if (filter === "builtin" && !builtin) return;
    if (filter === "custom" && builtin) return;
    if (config.enabled) {
      enabledCards.push({ key, config });
    } else {
      disabledCards.push({ key, config });
    }
  });

  return { enabledCards, disabledCards };
}, [channels, orderedKeys, filter, isBuiltin]);
```

- [ ] **Step 2: 提交代码**

```bash
git add console/src/pages/Control/Channels/index.tsx
git commit -m "refactor(channels): split cards into enabled and disabled arrays"
```

---

## Task 5: 修改 ChannelsPage 渲染逻辑

**Files:**
- Modify: `console/src/pages/Control/Channels/index.tsx:145-165`

- [ ] **Step 1: 导入新组件**

在文件顶部的导入语句中添加 `ChannelAvailableItem`：

```typescript
import {
  ChannelCard,
  ChannelDrawer,
  AccessControlDrawer,
  PendingApprovalsDrawer,
  useChannels,
  getChannelLabel,
  ChannelAvailableItem,
  type ChannelKey,
} from "./components";
```

- [ ] **Step 2: 替换渲染逻辑**

将现有的 `channelsGrid` 渲染部分替换为双区域布局：

```typescript
{loading ? (
  <div className={styles.loading}>
    <span className={styles.loadingText}>{t("channels.loading")}</span>
  </div>
) : (
  <>
    {/* Enabled Channels Section */}
    <div className={styles.panelSection}>
      <div className={styles.panelTitle}>
        <span className={styles.panelDotGreen} />
        {t("channels.enabledSection")}
        <span className={styles.panelCount}>
          {enabledCards.length} {t("channels.enabledCount", { count: "" })}
        </span>
      </div>

      {enabledCards.length > 0 ? (
        <div className={styles.channelsGrid}>
          {enabledCards.map(({ key, config }) => (
            <ChannelCard
              key={key}
              channelKey={key}
              config={config}
              onClick={() => handleCardClick(key)}
            />
          ))}
        </div>
      ) : (
        <div className={styles.emptyConfigured}>
          <p>{t("channels.noEnabledChannels")}</p>
          {disabledCards.length > 0 && (
            <Button
              type="primary"
              onClick={() => {
                document
                  .getElementById("available-channels")
                  ?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              {t("channels.goEnableChannels")}
            </Button>
          )}
        </div>
      )}
    </div>

    {/* Available Channels Section */}
    {disabledCards.length > 0 && (
      <div
        id="available-channels"
        className={styles.panelSectionDashed}
      >
        <div className={styles.panelTitle}>
          <span className={styles.panelDotGray} />
          {t("channels.availableSection")}
        </div>
        <div className={styles.availableGrid}>
          {disabledCards.map(({ key }) => (
            <ChannelAvailableItem
              key={key}
              channelKey={key}
              onClick={() => handleCardClick(key)}
            />
          ))}
        </div>
      </div>
    )}
  </>
)}
```

- [ ] **Step 3: 提交代码**

```bash
git add console/src/pages/Control/Channels/index.tsx
git commit -m "feat(channels): render enabled and disabled channels in separate sections"
```

---

## Task 6: 添加样式定义

**Files:**
- Modify: `console/src/pages/Control/Channels/index.module.less`

- [ ] **Step 1: 添加区域容器样式**

在 `index.module.less` 文件末尾（暗色模式之前）添加：

```less
/* ---- Panel Section Styles ---- */

.panelSection {
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 16px;
  margin: 16px 16px 0;
}

.panelSectionDashed {
  background: transparent;
  border: 1px dashed rgba(0, 0, 0, 0.15);
  border-radius: 12px;
  padding: 16px;
  margin: 16px;
}

.panelTitle {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: rgba(0, 0, 0, 0.5);
  margin-bottom: 16px;
}

.panelDotGreen {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
}

.panelDotGray {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.2);
}

.panelCount {
  color: #10b981;
  font-weight: 500;
}

.emptyConfigured {
  text-align: center;
  padding: 48px 24px;
  color: rgba(0, 0, 0, 0.45);

  p {
    margin: 0 0 16px;
    font-size: 14px;
  }
}
```

- [ ] **Step 2: 添加小卡片网格样式**

继续添加：

```less
/* ---- Available Grid Styles ---- */

.availableGrid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
}

.availableItem {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  background: rgba(255, 255, 255, 0.5);

  &:hover {
    background: rgba(0, 0, 0, 0.04);

    .availableItemAction {
      color: rgba(0, 0, 0, 0.88);
    }
  }
}

.availableItemName {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  color: rgba(0, 0, 0, 0.88);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.availableItemAction {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.45);
  flex-shrink: 0;
}
```

- [ ] **Step 3: 添加暗色模式样式**

在 `:global(.dark-mode)` 块中添加：

```less
:global(.dark-mode) {
  /* ... existing dark mode styles ... */

  .panelSection {
    background: rgba(255, 255, 255, 0.03);
    border-color: rgba(255, 255, 255, 0.06);
  }

  .panelSectionDashed {
    background: transparent;
    border-color: rgba(255, 255, 255, 0.1);
  }

  .panelTitle {
    color: rgba(255, 255, 255, 0.5);
  }

  .panelDotGreen {
    background: #34d399;
  }

  .panelDotGray {
    background: rgba(255, 255, 255, 0.2);
  }

  .panelCount {
    color: #34d399;
  }

  .emptyConfigured {
    color: rgba(255, 255, 255, 0.45);
  }

  .availableItem {
    background: rgba(255, 255, 255, 0.03);

    &:hover {
      background: rgba(255, 255, 255, 0.06);

      .availableItemAction {
        color: rgba(255, 255, 255, 0.85);
      }
    }
  }

  .availableItemName {
    color: rgba(255, 255, 255, 0.85);
  }

  .availableItemAction {
    color: rgba(255, 255, 255, 0.45);
  }
}
```

- [ ] **Step 4: 添加移动端响应式样式**

在 `@media (max-width: 768px)` 块中添加：

```less
@media (max-width: 768px) {
  /* ... existing mobile styles ... */

  .panelSection,
  .panelSectionDashed {
    margin: 12px;
    padding: 12px;
  }

  .panelTitle {
    font-size: 12px;
    margin-bottom: 12px;
  }

  .availableGrid {
    grid-template-columns: 1fr;
  }

  .availableItem {
    padding: 8px 12px;
  }

  .emptyConfigured {
    padding: 32px 16px;
  }
}
```

- [ ] **Step 5: 提交代码**

```bash
git add console/src/pages/Control/Channels/index.module.less
git commit -m "feat(channels): add styles for dual-section layout and available items"
```

---

## Task 7: 运行格式化并验证

**Files:**
- None (command execution only)

- [ ] **Step 1: 运行代码格式化**

```bash
cd console
npm run format
```

- [ ] **Step 2: 检查 lint 错误**

```bash
npm run lint
```

Expected: No errors related to the changes

- [ ] **Step 3: 提交格式化后的代码**

```bash
git add .
git commit -m "style: format code"
```

---

## Task 8: 手动测试验证

**Files:**
- None (manual testing)

- [ ] **Step 1: 启动开发服务器**

```bash
cd console
npm run dev
```

- [ ] **Step 2: 测试已激活频道显示**

- 打开频道页面
- 验证已激活频道显示在大卡片区域
- 验证区域标题显示 "已激活 X 个"
- 验证点击卡片打开 Drawer

- [ ] **Step 3: 测试未激活频道显示**

- 验证未激活频道显示在小卡片区域
- 验证区域标题显示 "未激活"
- 验证小卡片显示图标、名称和"启用"按钮
- 验证点击小卡片打开 Drawer

- [ ] **Step 4: 测试筛选功能**

- 切换到"内置"筛选
- 验证两个区域都只显示内置频道
- 切换到"自定义"筛选
- 验证两个区域都只显示自定义频道

- [ ] **Step 5: 测试空状态**

- 如果所有频道都已激活，验证未激活区域不显示
- 如果所有频道都未激活，验证已激活区域显示空状态提示和引导按钮

- [ ] **Step 6: 测试响应式布局**

- 调整浏览器窗口大小到移动端尺寸
- 验证大卡片变为单列
- 验证小卡片变为单列

- [ ] **Step 7: 测试暗色模式**

- 切换到暗色模式
- 验证区域容器、标题、小卡片的样式正确

- [ ] **Step 8: 提交最终代码**

```bash
git add .
git commit -m "feat(channels): complete dual-section layout implementation"
```

---

## 完成标准

- ✅ 已激活频道显示在大卡片区域，带绿色圆点标题和数量统计
- ✅ 未激活频道显示在小卡片区域，带灰色圆点标题和虚线边框
- ✅ 小卡片显示图标、名称和"启用"按钮（极简版）
- ✅ 筛选功能对两个区域都生效
- ✅ 空状态处理正确
- ✅ 响应式布局正确（桌面端和移动端）
- ✅ 暗色模式样式正确
- ✅ 代码格式化完成，无 lint 错误
- ✅ 所有手动测试通过
