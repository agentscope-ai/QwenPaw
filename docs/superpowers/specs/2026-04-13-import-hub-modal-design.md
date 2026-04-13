# ImportHubModal 改进设计文档

**日期**: 2026-04-13  
**状态**: 待审核  
**相关组件**: `console/src/pages/Agent/Skills/components/ImportHubModal.tsx`

---

## 1. 设计目标

### 当前问题
- URL输入框在底部，用户可能先困惑于卡片区域
- 示例URL被截断显示，看起来像可点击按钮但实际是文本
- 卡片标题可跳转外部，与"选择来源"的意图冲突
- 6个卡片平铺，视觉层次弱，无主次之分
- 缺少品牌图标，难以快速识别各个平台

### 改进目标
1. **清晰引导**: 明确告知用户"粘贴URL"是主要操作
2. **简化视觉**: 减少信息噪音，优化布局层次
3. **改善交互**: 示例URL可点击填充，而非直接跳转
4. **提升美感**: 添加平台图标，优化卡片设计

---

## 2. 整体布局

### 2.1 Modal 规格

| 属性 | 值 | 说明 |
|------|-----|------|
| 宽度 | 680px | 比当前760px略窄，更紧凑 |
| 最大高度 | 85vh | 防止超长内容溢出 |
| 圆角 | 12px | 符合设计系统 |
| 背景遮罩 | rgba(0, 0, 0, 0.45) | 标准遮罩色 |

### 2.2 内容区域划分

```
┌──────────────────────────────────────────────────────────┐
│ Header: Import from Skill Hub                       [✕]  │
├──────────────────────────────────────────────────────────┤
│                                                          │
│ Section 1: URL Input (Primary)                           │
│ ┌────────────────────────────────────────────────────┐   │
│ │ [🔗] [input]                                  [📋] │   │
│ └────────────────────────────────────────────────────┘   │
│ [Validation Message]                                     │
│                                                          │
│ Divider: ────── or choose from popular sources ──────   │
│                                                          │
│ Section 2: Source Cards Grid                             │
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐   │
│ │Card 1│ │Card 2│ │Card 3│ │Card 4│ │Card 5│ │Card 6│   │
│ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘   │
│                                                          │
│ Section 3: Examples Panel (Conditional)                  │
│ ┌────────────────────────────────────────────────────┐   │
│ │ 📎 Examples from {SourceName}:                     │   │
│ │ • example-url-1                                    │   │
│ │ • example-url-2                                    │   │
│ └────────────────────────────────────────────────────┘   │
│                                                          │
│ Footer:                              [Cancel] [Import]   │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 详细设计

### 3.1 Section 1: URL 输入区

#### 输入框设计

```less
.importUrlInputWrapper {
  position: relative;
  display: flex;
  align-items: center;
  border: 1px solid #d9d9d9;
  border-radius: 10px;
  background: #fff;
  transition: all 0.2s ease;
  padding: 0 12px;
  height: 48px;

  &:hover {
    border-color: #615ced;
  }

  &:focus-within {
    border-color: #615ced;
    box-shadow: 0 0 0 3px rgba(97, 92, 237, 0.1);
  }

  // 状态变体
  &.valid {
    border-color: #52c41a;
    background: rgba(82, 196, 26, 0.02);
  }

  &.invalid {
    border-color: #ff4d4f;
    background: rgba(255, 77, 79, 0.02);
  }

  &.loading {
    border-color: #615ced;
  }
}

.importUrlIcon {
  color: #999;
  font-size: 16px;
  margin-right: 10px;
  flex-shrink: 0;
}

.importUrlInput {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: 14px;
  color: #1a1a1a;
  
  &::placeholder {
    color: #bfbfbf;
  }
}

.importUrlActions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.pasteButton {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #999;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;

  &:hover {
    background: rgba(97, 92, 237, 0.08);
    color: #615ced;
  }
}

.clearButton {
  // 同 pasteButton 样式
}
```

#### 验证状态反馈

| 状态 | 视觉 | 文案示例 |
|------|------|----------|
| 默认 | 灰色边框 | - |
| 输入中 | 紫色边框 + 微弱发光 | - |
| 验证中 | 紫色边框 + Input内右侧Spinner | "验证中..." |
| 有效 | 绿色边框 + 绿色勾选图标 | "✓ 检测到 Skills.sh 链接" |
| 无效 | 红色边框 + 红色错误图标 | "✗ 不支持的来源，请使用下方支持的来源" |
| 未找到 | 红色边框 | "✗ 无法访问该链接，请检查URL" |

```typescript
// 验证状态组件
interface ValidationStatusProps {
  status: 'default' | 'validating' | 'valid' | 'invalid' | 'notfound';
  source?: string;  // 检测到的来源名称
  message?: string;
}
```

```less
.validationStatus {
  margin-top: 8px;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;

  &.valid {
    color: #52c41a;
  }

  &.invalid,
  &.notfound {
    color: #ff4d4f;
  }

  &.validating {
    color: #615ced;
  }
}
```

---

### 3.2 Section 2: 来源卡片网格

#### 卡片布局

```less
.sourcesGrid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 16px;
}

.sourceCard {
  position: relative;
  padding: 16px 12px;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  text-align: center;

  &:hover {
    border-color: #615ced;
    box-shadow: 0 4px 12px rgba(97, 92, 237, 0.12);
    transform: translateY(-2px);
  }

  &.active {
    border-color: #615ced;
    background: rgba(97, 92, 237, 0.04);
    box-shadow: 0 0 0 2px rgba(97, 92, 237, 0.15);
  }

  &.disabled {
    opacity: 0.5;
    cursor: not-allowed;
    
    &:hover {
      border-color: #e8e8e8;
      box-shadow: none;
      transform: none;
    }
  }
}

.sourceCardIcon {
  width: 40px;
  height: 40px;
  margin: 0 auto 10px;
  border-radius: 10px;
  background: #f5f5f5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  transition: all 0.2s ease;

  .sourceCard:hover & {
    background: rgba(97, 92, 237, 0.1);
    transform: scale(1.05);
  }
}

.sourceCardName {
  font-size: 14px;
  font-weight: 600;
  color: #1a1a1a;
  margin-bottom: 4px;
}

.sourceCardMeta {
  font-size: 12px;
  color: #999;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.sourceCardArrow {
  font-size: 10px;
  transition: transform 0.2s ease;

  .sourceCard.active & {
    transform: rotate(180deg);
  }
}

// 外部链接小图标
.sourceCardExternal {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #d9d9d9;
  font-size: 12px;
  transition: all 0.2s ease;

  &:hover {
    background: rgba(97, 92, 237, 0.08);
    color: #615ced;
  }
}
```

#### 平台图标映射

| 平台 | 图标 | 备选 |
|------|------|------|
| Skills.sh | 🛠️ | WrenchOutlined |
| ClawHub | 🐾 | CodeOutlined |
| SkillsMP | 📦 | AppstoreOutlined |
| LobeHub | 🧠 | RobotOutlined |
| GitHub | 🐙 | GithubOutlined |
| ModelScope | 🔬 | ExperimentOutlined |

---

### 3.3 Section 3: 示例面板

```less
.examplesPanel {
  margin-top: 16px;
  padding: 16px;
  background: #fafafa;
  border-radius: 10px;
  border: 1px solid #f0f0f0;
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.examplesPanelHeader {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #666;
  margin-bottom: 12px;
  font-weight: 500;
}

.examplesList {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.exampleItem {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 13px;
  color: #333;

  &:hover {
    border-color: #615ced;
    background: rgba(97, 92, 237, 0.02);
    color: #615ced;
  }

  &:active {
    transform: scale(0.995);
  }
}

.exampleItemIcon {
  margin-right: 10px;
  color: #bfbfbf;
  font-size: 14px;
}

.exampleItemLabel {
  margin-left: auto;
  font-size: 11px;
  color: #999;
  background: #f5f5f5;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: system-ui, sans-serif;
}
```

---

### 3.4 Footer 按钮

```less
.modalFooter {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #f0f0f0;
}

.cancelButton {
  min-width: 88px;
}

.importButton {
  min-width: 120px;
}
```

---

## 4. 交互流程

### 4.1 状态机

```
[初始状态]
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  • URL输入框为空                                            │
│  • 来源卡片均未选中                                         │
│  • 示例面板隐藏                                             │
│  • Import按钮禁用                                           │
└─────────────────────────────────────────────────────────────┘
    │
    ├─────────────────────────────────────────────────────────┐
    │ 用户粘贴URL                                             │
    ▼                                                         │
┌─────────────────────────────────────────────────────────────┐
│ [验证状态]                                                  │
│  • 显示"验证中..."                                          │
│  • 边框变紫色                                               │
└─────────────────────────────────────────────────────────────┘
    │
    ├── 有效 ───► ┌──────────────────────────────────────────┐
    │             │  • 边框变绿色                              │
    │             │  • 显示"✓ 检测到 {来源}"                   │
    │             │  • Import按钮启用                          │
    │             └──────────────────────────────────────────┘
    │
    └── 无效 ───► ┌──────────────────────────────────────────┐
                  │  • 边框变红色                              │
                  │  • 显示错误提示                            │
                  │  • Import按钮禁用                          │
                  └──────────────────────────────────────────┘
    │
    │ 用户点击来源卡片
    ▼
┌─────────────────────────────────────────────────────────────┐
│ [展开状态]                                                  │
│  • 卡片高亮（紫色边框+背景）                                │
│  • 下方展开示例面板                                         │
│  • 点击示例填充到URL输入框                                  │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 验证逻辑

```typescript
// 伪代码
async function validateUrl(url: string): Promise<ValidationResult> {
  // 1. 检查是否为空
  if (!url.trim()) return { status: 'default' };
  
  // 2. 检查格式是否有效
  if (!isValidUrlFormat(url)) {
    return { status: 'invalid', message: '请输入有效的URL' };
  }
  
  // 3. 检查是否支持
  const source = detectSource(url);
  if (!source) {
    return { status: 'invalid', message: '不支持的来源' };
  }
  
  // 4. 可选：验证可访问性（异步）
  setStatus('validating');
  const accessible = await checkAccessibility(url);
  
  if (!accessible) {
    return { status: 'notfound', message: '无法访问该链接' };
  }
  
  return { status: 'valid', source: source.name };
}
```

---

## 5. 暗色模式

```less
:global(.dark-mode) {
  .importUrlInputWrapper {
    background: #2a2a2a;
    border-color: rgba(255, 255, 255, 0.15);
    
    &:hover,
    &:focus-within {
      border-color: #615ced;
    }
    
    &.valid {
      border-color: #4ade80;
      background: rgba(82, 196, 26, 0.05);
    }
    
    &.invalid {
      border-color: #ff6b6b;
      background: rgba(255, 77, 79, 0.05);
    }
  }

  .importUrlInput {
    color: rgba(255, 255, 255, 0.9);
    
    &::placeholder {
      color: rgba(255, 255, 255, 0.3);
    }
  }

  .sourceCard {
    background: #1f1f1f;
    border-color: rgba(255, 255, 255, 0.1);
    
    &:hover {
      border-color: #615ced;
      background: rgba(97, 92, 237, 0.08);
    }
    
    &.active {
      background: rgba(97, 92, 237, 0.12);
    }
  }

  .sourceCardName {
    color: rgba(255, 255, 255, 0.9);
  }

  .sourceCardIcon {
    background: rgba(255, 255, 255, 0.08);
  }

  .examplesPanel {
    background: rgba(255, 255, 255, 0.03);
    border-color: rgba(255, 255, 255, 0.1);
  }

  .exampleItem {
    background: #2a2a2a;
    border-color: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.85);
    
    &:hover {
      border-color: #615ced;
      background: rgba(97, 92, 237, 0.08);
      color: #8b87f0;
    }
  }

  .examplesPanelHeader {
    color: rgba(255, 255, 255, 0.6);
  }

  .modalFooter {
    border-color: rgba(255, 255, 255, 0.1);
  }
}
```

---

## 6. 响应式适配

### 移动端 (< 640px)

```less
@media (max-width: 640px) {
  .importHubModal {
    width: 100% !important;
    max-width: 100%;
    margin: 0;
    top: 0;
    border-radius: 0;
    height: 100vh;
    
    :global(.ant-modal-content) {
      border-radius: 0;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    
    :global(.ant-modal-body) {
      flex: 1;
      overflow-y: auto;
    }
  }

  .sourcesGrid {
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
  }

  .sourceCard {
    padding: 12px 8px;
  }

  .sourceCardIcon {
    width: 36px;
    height: 36px;
    font-size: 18px;
  }

  .exampleItem {
    font-size: 12px;
    padding: 8px 10px;
    word-break: break-all;
  }
}
```

---

## 7. 无障碍 (A11y)

### 键盘导航

- `Tab`: 在URL输入框、卡片、按钮之间循环
- `Enter`: 
  - 在输入框中：触发验证
  - 在卡片上：展开/收起示例
  - 在示例上：填充URL
- `Escape`: 关闭Modal
- `Ctrl+V` / `Cmd+V`: 粘贴到URL输入框

### ARIA 属性

```tsx
// URL输入框
<input
  aria-label="Skill URL"
  aria-describedby={validationId}
  aria-invalid={isInvalid}
/>

// 验证状态
<div id={validationId} role="status" aria-live="polite">
  {validationMessage}
</div>

// 来源卡片
<button
  role="button"
  aria-expanded={isExpanded}
  aria-controls={examplesPanelId}
  aria-label={`${sourceName}, ${exampleCount} examples`}
>

// 示例面板
<div
  id={examplesPanelId}
  role="region"
  aria-label={`${sourceName} examples`}
>
```

---

## 8. 组件结构

### 文件变更

```
console/src/pages/Agent/Skills/
├── components/
│   ├── ImportHubModal.tsx          # 重写
│   └── ImportHubModal.module.less  # 新增样式文件
├── index.module.less               # 移除旧样式 (line 84-216, 759-776)
```

### 组件拆分

```typescript
// ImportHubModal.tsx 内部组件

// 1. URLInputSection - URL输入区
interface URLInputSectionProps {
  value: string;
  onChange: (value: string) => void;
  validation: ValidationState;
  onPaste: () => void;
}

// 2. SourceCard - 来源卡片
interface SourceCardProps {
  market: SkillMarket;
  isActive: boolean;
  onClick: () => void;
  icon: React.ReactNode;
}

// 3. ExamplesPanel - 示例面板
interface ExamplesPanelProps {
  source: SkillMarket;
  onSelect: (url: string) => void;
}

// 4. ValidationStatus - 验证状态
interface ValidationStatusProps {
  status: ValidationStatusType;
  source?: string;
}
```

---

## 9. 实现检查清单

### 功能
- [ ] URL输入框支持粘贴
- [ ] 实时验证（带防抖 300ms）
- [ ] 来源卡片点击展开示例
- [ ] 示例点击填充到输入框
- [ ] Import按钮状态随验证结果变化
- [ ] 支持键盘导航
- [ ] 暗色模式样式
- [ ] 移动端适配

### 样式
- [ ] 所有颜色使用设计系统变量
- [ ] 过渡动画流畅（0.2s ease）
- [ ] 悬停状态清晰
- [ ] 焦点状态可见

### 无障碍
- [ ] 键盘可完全操作
- [ ] ARIA属性完整
- [ ] 颜色对比度符合WCAG 2.1 AA

---

## 10. 参考资源

- [Carbon Design System - Import Pattern](https://carbondesignsystem.com/community/patterns/import-pattern)
- [VS Code Extension Marketplace](https://marketplace.visualstudio.com/)
- [LobeHub Skills](https://lobehub.com/skills)
- [Ant Design Modal](https://ant.design/components/modal)

---

**下一步**: 审核通过后，创建具体实现计划。
