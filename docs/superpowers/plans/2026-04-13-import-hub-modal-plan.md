# ImportHubModal 改进实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 ImportHubModal 组件，改善视觉设计和用户体验，使URL输入更清晰，来源选择更直观。

**Architecture:** 使用现有的 `@agentscope-ai/design` 组件库（基于 Ant Design），采用模块化组件拆分，新增独立样式文件，保持与现有设计系统一致。

**Tech Stack:** React + TypeScript + Less + @agentscope-ai/design (Ant Design)

**参考文档:** `docs/superpowers/specs/2026-04-13-import-hub-modal-design.md`

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `console/src/pages/Agent/Skills/components/ImportHubModal.tsx` | 重写 | 重构整个Modal组件 |
| `console/src/pages/Agent/Skills/components/ImportHubModal.module.less` | 创建 | 新增样式文件 |
| `console/src/pages/Agent/Skills/index.module.less` | 修改 | 移除旧样式 (line 84-216, 759-776) |

---

## Task 1: 创建新的样式文件

**目标:** 创建独立的样式文件 ImportHubModal.module.less

**文件:**
- 创建: `console/src/pages/Agent/Skills/components/ImportHubModal.module.less`

### 步骤

- [ ] **Step 1.1: 创建基础容器样式**

```less
.importHubModal {
  :global {
    .ant-modal-content {
      border-radius: 12px;
    }
    
    .ant-modal-header {
      border-bottom: 1px solid #f0f0f0;
      padding: 20px 24px;
    }
    
    .ant-modal-body {
      padding: 24px;
    }
    
    .ant-modal-footer {
      border-top: 1px solid #f0f0f0;
      padding: 16px 24px;
    }
  }
}
```

- [ ] **Step 1.2: 添加URL输入区样式**

```less
.urlInputSection {
  margin-bottom: 20px;
}

.sectionLabel {
  font-size: 14px;
  font-weight: 500;
  color: #1a1a1a;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.inputWrapper {
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

  &.valid {
    border-color: #52c41a;
    background: rgba(82, 196, 26, 0.02);
  }

  &.invalid {
    border-color: #ff4d4f;
    background: rgba(255, 77, 79, 0.02);
  }
}

.inputIcon {
  color: #999;
  font-size: 16px;
  margin-right: 10px;
  flex-shrink: 0;
}

.urlInput {
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

.inputActions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.iconButton {
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
  font-size: 14px;

  &:hover {
    background: rgba(97, 92, 237, 0.08);
    color: #615ced;
  }
}
```

- [ ] **Step 1.3: 添加验证状态样式**

```less
.validationStatus {
  margin-top: 8px;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 20px;

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

.validationIcon {
  font-size: 14px;
}
```

- [ ] **Step 1.4: 添加分隔线样式**

```less
.divider {
  display: flex;
  align-items: center;
  margin: 20px 0;
  color: #999;
  font-size: 13px;
  
  &::before,
  &::after {
    content: '';
    flex: 1;
    height: 1px;
    background: #f0f0f0;
  }
  
  &::before {
    margin-right: 12px;
  }
  
  &::after {
    margin-left: 12px;
  }
}
```

- [ ] **Step 1.5: 添加来源卡片网格样式**

```less
.sourcesGrid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
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

.externalLink {
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
  text-decoration: none;
  transition: all 0.2s ease;

  &:hover {
    background: rgba(97, 92, 237, 0.08);
    color: #615ced;
  }
}
```

- [ ] **Step 1.6: 添加示例面板样式**

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

.examplesHeader {
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
  text-align: left;
  width: 100%;

  &:hover {
    border-color: #615ced;
    background: rgba(97, 92, 237, 0.02);
    color: #615ced;
  }

  &:active {
    transform: scale(0.995);
  }
}

.exampleIcon {
  margin-right: 10px;
  color: #bfbfbf;
  font-size: 14px;
  flex-shrink: 0;
}

.exampleUrl {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 1.7: 添加暗色模式样式**

```less
:global(.dark-mode) {
  .inputWrapper {
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

  .urlInput {
    color: rgba(255, 255, 255, 0.9);
    
    &::placeholder {
      color: rgba(255, 255, 255, 0.3);
    }
  }

  .sectionLabel {
    color: rgba(255, 255, 255, 0.9);
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

  .examplesHeader {
    color: rgba(255, 255, 255, 0.6);
  }

  .divider {
    color: rgba(255, 255, 255, 0.4);
    
    &::before,
    &::after {
      background: rgba(255, 255, 255, 0.1);
    }
  }
}
```

- [ ] **Step 1.8: 提交样式文件**

```bash
cd /Users/bw/dev/QwenPaw
git add console/src/pages/Agent/Skills/components/ImportHubModal.module.less
git commit -m "feat: add ImportHubModal styles with dark mode support"
```

---

## Task 2: 重构 ImportHubModal 组件

**目标:** 重写 ImportHubModal.tsx，实现新的交互和视觉设计

**文件:**
- 重写: `console/src/pages/Agent/Skills/components/ImportHubModal.tsx`

### 步骤

- [ ] **Step 2.1: 更新导入语句**

```typescript
import { useState, useCallback, useMemo } from "react";
import { Button, Modal, Spin } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { 
  ExportOutlined, 
  LinkOutlined, 
  CopyOutlined, 
  CloseOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DownOutlined,
  PaperClipOutlined
} from "@ant-design/icons";
import { isSupportedSkillUrl, skillMarkets, type SkillMarket } from "./index";
import styles from "./ImportHubModal.module.less";

// 平台图标映射
const MARKET_ICONS: Record<string, string> = {
  "skills.sh": "🛠️",
  "clawhub": "🐾",
  "skillsmp": "📦",
  "lobehub": "🧠",
  "github": "🐙",
  "modelscope": "🔬",
};
```

- [ ] **Step 2.2: 添加类型定义和辅助函数**

```typescript
type ValidationStatus = "default" | "validating" | "valid" | "invalid" | "notfound";

interface ValidationState {
  status: ValidationStatus;
  message?: string;
  source?: string;
}

interface ImportHubModalProps {
  open: boolean;
  importing: boolean;
  onCancel: () => void;
  onConfirm: (url: string, targetName?: string) => Promise<void>;
  cancelImport?: () => void;
  hint?: string;
}

// 检测URL来源
function detectSource(url: string): SkillMarket | undefined {
  return skillMarkets.find(market => 
    url.toLowerCase().includes(market.urlPrefix.toLowerCase())
  );
}

// 验证URL
async function validateSkillUrl(url: string): Promise<ValidationState> {
  if (!url.trim()) {
    return { status: "default" };
  }
  
  // 基本格式验证
  try {
    new URL(url);
  } catch {
    return { status: "invalid", message: "请输入有效的URL" };
  }
  
  // 检测来源
  const source = detectSource(url);
  if (!source) {
    return { status: "invalid", message: "不支持的来源" };
  }
  
  // 验证支持的URL格式
  if (!isSupportedSkillUrl(url)) {
    return { status: "invalid", message: "URL格式不正确" };
  }
  
  return { status: "valid", source: source.name };
}
```

- [ ] **Step 2.3: 实现主组件结构**

```typescript
export function ImportHubModal({
  open,
  importing,
  onCancel,
  onConfirm,
  cancelImport,
  hint,
}: ImportHubModalProps) {
  const { t } = useTranslation();
  const [importUrl, setImportUrl] = useState("");
  const [validation, setValidation] = useState<ValidationState>({ status: "default" });
  const [activeMarket, setActiveMarket] = useState<string | null>(null);

  // 重置状态
  const handleClose = useCallback(() => {
    if (importing) return;
    setImportUrl("");
    setValidation({ status: "default" });
    setActiveMarket(null);
    onCancel();
  }, [importing, onCancel]);

  // 处理URL变化
  const handleUrlChange = useCallback(async (value: string) => {
    setImportUrl(value);
    
    if (!value.trim()) {
      setValidation({ status: "default" });
      return;
    }
    
    setValidation({ status: "validating" });
    
    // 防抖验证
    const result = await validateSkillUrl(value);
    setValidation(result);
  }, []);

  // 粘贴功能
  const handlePaste = useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText();
      handleUrlChange(text);
    } catch {
      // 粘贴失败静默处理
    }
  }, [handleUrlChange]);

  // 清空输入
  const handleClear = useCallback(() => {
    setImportUrl("");
    setValidation({ status: "default" });
  }, []);

  // 选择示例
  const handleSelectExample = useCallback((url: string) => {
    handleUrlChange(url);
  }, [handleUrlChange]);

  // 切换来源卡片
  const toggleMarket = useCallback((key: string) => {
    setActiveMarket(prev => prev === key ? null : key);
  }, []);

  // 确认导入
  const handleConfirm = useCallback(async () => {
    if (importing) return;
    const trimmed = importUrl.trim();
    if (!trimmed) return;
    if (validation.status !== "valid") return;
    
    await onConfirm(trimmed);
  }, [importUrl, importing, validation.status, onConfirm]);

  // 是否可以导入
  const canImport = validation.status === "valid" && !importing;

  return (
    <Modal
      className={styles.importHubModal}
      title={t("skills.importHub")}
      open={open}
      onCancel={handleClose}
      keyboard={!importing}
      closable={!importing}
      maskClosable={!importing}
      width={680}
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
          <Button
            onClick={importing && cancelImport ? cancelImport : handleClose}
          >
            {t(importing && cancelImport ? "skills.cancelImport" : "common.cancel")}
          </Button>
          <Button
            type="primary"
            onClick={handleConfirm}
            loading={importing}
            disabled={!canImport}
          >
            {t("skills.importHub")}
          </Button>
        </div>
      }
    >
      {/* URL输入区 */}
      <div className={styles.urlInputSection}>
        <div className={styles.sectionLabel}>
          <LinkOutlined />
          {t("skills.enterSkillUrl")}
        </div>
        
        <div className={`${styles.inputWrapper} ${styles[validation.status]}`}>
          <LinkOutlined className={styles.inputIcon} />
          <input
            className={styles.urlInput}
            value={importUrl}
            onChange={(e) => handleUrlChange(e.target.value)}
            placeholder="https://..."
            disabled={importing}
            aria-label="Skill URL"
          />
          <div className={styles.inputActions}>
            {importUrl && (
              <button 
                className={styles.iconButton} 
                onClick={handleClear}
                title="Clear"
              >
                <CloseOutlined />
              </button>
            )}
            <button 
              className={styles.iconButton} 
              onClick={handlePaste}
              title="Paste from clipboard"
            >
              <CopyOutlined />
            </button>
          </div>
        </div>

        {/* 验证状态 */}
        <ValidationStatus validation={validation} />
      </div>

      {/* 分隔线 */}
      <div className={styles.divider}>
        {t("skills.orChooseFromSources")}
      </div>

      {/* 来源卡片网格 */}
      <div className={styles.sourcesGrid}>
        {skillMarkets.map((market) => (
          <SourceCard
            key={market.key}
            market={market}
            isActive={activeMarket === market.key}
            onClick={() => toggleMarket(market.key)}
          />
        ))}
      </div>

      {/* 示例面板 */}
      {activeMarket && (
        <ExamplesPanel
          market={skillMarkets.find(m => m.key === activeMarket)!}
          onSelect={handleSelectExample}
        />
      )}

      {/* 导入中提示 */}
      {importing && (
        <div style={{ marginTop: 16, textAlign: "center", color: "#666" }}>
          <Spin size="small" style={{ marginRight: 8 }} />
          {t("common.loading")}
        </div>
      )}
    </Modal>
  );
}
```

- [ ] **Step 2.4: 实现 ValidationStatus 子组件**

```typescript
interface ValidationStatusProps {
  validation: ValidationState;
}

function ValidationStatus({ validation }: ValidationStatusProps) {
  const { t } = useTranslation();
  
  if (validation.status === "default") {
    return <div className={styles.validationStatus} />;
  }
  
  if (validation.status === "validating") {
    return (
      <div className={`${styles.validationStatus} ${styles.validating}`}>
        <Spin size="small" style={{ marginRight: 6 }} />
        {t("skills.validatingUrl")}
      </div>
    );
  }
  
  if (validation.status === "valid") {
    return (
      <div className={`${styles.validationStatus} ${styles.valid}`}>
        <CheckCircleOutlined className={styles.validationIcon} />
        {t("skills.urlValid", { source: validation.source })}
      </div>
    );
  }
  
  return (
    <div className={`${styles.validationStatus} ${styles[validation.status]}`}>
      <CloseCircleOutlined className={styles.validationIcon} />
      {validation.message || t("skills.invalidUrl")}
    </div>
  );
}
```

- [ ] **Step 2.5: 实现 SourceCard 子组件**

```typescript
interface SourceCardProps {
  market: SkillMarket;
  isActive: boolean;
  onClick: () => void;
}

function SourceCard({ market, isActive, onClick }: SourceCardProps) {
  const icon = MARKET_ICONS[market.key] || "📦";
  const exampleCount = market.examples.length;
  
  return (
    <div
      className={`${styles.sourceCard} ${isActive ? styles.active : ""}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      aria-expanded={isActive}
    >
      <a
        href={market.homepage}
        target="_blank"
        rel="noopener noreferrer"
        className={styles.externalLink}
        onClick={(e) => e.stopPropagation()}
        title={market.homepage}
      >
        <ExportOutlined />
      </a>
      
      <div className={styles.sourceCardIcon}>{icon}</div>
      <div className={styles.sourceCardName}>{market.name}</div>
      <div className={styles.sourceCardMeta}>
        {exampleCount > 0 && (
          <>
            {exampleCount} examples
            <DownOutlined className={styles.sourceCardArrow} />
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2.6: 实现 ExamplesPanel 子组件**

```typescript
interface ExamplesPanelProps {
  market: SkillMarket;
  onSelect: (url: string) => void;
}

function ExamplesPanel({ market, onSelect }: ExamplesPanelProps) {
  const { t } = useTranslation();
  
  if (market.examples.length === 0) return null;
  
  return (
    <div className={styles.examplesPanel}>
      <div className={styles.examplesHeader}>
        <PaperClipOutlined />
        {t("skills.examplesFrom", { source: market.name })}
      </div>
      <div className={styles.examplesList}>
        {market.examples.map((example, idx) => (
          <button
            key={idx}
            className={styles.exampleItem}
            onClick={() => onSelect(example.url)}
            title={t("skills.clickToFill")}
          >
            <LinkOutlined className={styles.exampleIcon} />
            <span className={styles.exampleUrl}>{example.url}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2.7: 添加翻译键值（可选）**

如果需要新的翻译键值，检查 `console/src/i18n/` 目录下的翻译文件，添加：

```json
{
  "skills": {
    "orChooseFromSources": "or choose from popular sources",
    "validatingUrl": "Validating URL...",
    "urlValid": "Valid URL from {{source}}",
    "invalidUrl": "Invalid URL",
    "examplesFrom": "Examples from {{source}}",
    "clickToFill": "Click to fill in URL"
  }
}
```

- [ ] **Step 2.8: 提交组件重构**

```bash
cd /Users/bw/dev/QwenPaw
git add console/src/pages/Agent/Skills/components/ImportHubModal.tsx
git commit -m "feat: refactor ImportHubModal with improved UI and UX"
```

---

## Task 3: 清理旧样式

**目标:** 从 index.module.less 中移除已迁移的旧样式

**文件:**
- 修改: `console/src/pages/Agent/Skills/index.module.less`

### 步骤

- [ ] **Step 3.1: 删除旧样式**

在 `index.module.less` 中删除以下部分：

```less
// 删除 line 84-216
.importMarketsSection { ... }
.importSectionTitle { ... }
.importMarketsGrid { ... }
.marketCard { ... }
.marketCardHeader { ... }
.marketName { ... }
.marketArrow { ... }
.marketExamples { ... }
.examplesLabel { ... }
.exampleTags { ... }
.exampleTag { ... }
.importUrlInput { ... }
.importUrlError { ... }
.importLoadingText { ... }
```

```less
// 删除 line 759-776 (检查实际行号)
.importHubModal { ... }
```

- [ ] **Step 3.2: 验证删除**

确认 `index.module.less` 中不再包含 `.importHubModal`、`.marketCard`、`.exampleTag` 等样式。

- [ ] **Step 3.3: 提交清理**

```bash
cd /Users/bw/dev/QwenPaw
git add console/src/pages/Agent/Skills/index.module.less
git commit -m "refactor: remove old ImportHubModal styles (moved to module file)"
```

---

## Task 4: 验证和测试

**目标:** 确保重构后的组件正常工作

### 步骤

- [ ] **Step 4.1: 类型检查**

```bash
cd /Users/bw/dev/QwenPaw/console
npx tsc --noEmit
```

预期: 无类型错误

- [ ] **Step 4.2: 代码格式检查**

```bash
cd /Users/bw/dev/QwenPaw/console
npm run lint
npm run format
```

- [ ] **Step 4.3: 运行前端构建**

```bash
cd /Users/bw/dev/QwenPaw/console
npm run build
```

预期: 构建成功，无错误

- [ ] **Step 4.4: 手动测试清单**

在浏览器中打开 Console，测试 ImportHubModal：

- [ ] Modal 正常打开/关闭
- [ ] URL 输入框可以输入和粘贴
- [ ] 验证状态正确显示（有效/无效/验证中）
- [ ] 来源卡片悬停有效果
- [ ] 点击卡片展开示例面板
- [ ] 点击示例自动填充URL
- [ ] Import按钮状态随验证结果变化
- [ ] 暗色模式样式正确

- [ ] **Step 4.5: 提交验证**

```bash
cd /Users/bw/dev/QwenPaw
git log --oneline -5
```

确认有3个commit：
1. "feat: add ImportHubModal styles with dark mode support"
2. "feat: refactor ImportHubModal with improved UI and UX"
3. "refactor: remove old ImportHubModal styles..."

---

## 执行检查清单

### 功能检查
- [ ] URL输入和验证正常工作
- [ ] 粘贴按钮可用
- [ ] 来源卡片展开/收起正常
- [ ] 示例点击填充URL
- [ ] Import按钮状态正确
- [ ] 加载状态显示

### 样式检查
- [ ] 所有状态样式正确（默认/悬停/激活/验证）
- [ ] 暗色模式样式正确
- [ ] 动画流畅
- [ ] 响应式布局正常

### 代码质量
- [ ] TypeScript 无错误
- [ ] ESLint 通过
- [ ] 代码格式正确
- [ ] 构建成功

---

**计划完成！**

保存路径: `docs/superpowers/plans/2026-04-13-import-hub-modal-plan.md`

**下一步:** 使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行此计划。
