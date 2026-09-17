# WeldonAgent External Branding and Path Privacy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一所有普通用户可见品牌为 WeldonAgent，隐藏版本、上游入口、物理目录与内部智能体 ID，同时保留内部兼容标识。

**Architecture:** 在前端建立单一 `brand.ts` 配置源，登录、页头、聊天和错误/空状态全部消费该配置。路径隐私通过展示模型解决：API 仍按现有权限返回运行所需字段，但普通组件只显示智能体展示名和逻辑工作区名，不把物理路径写入 DOM、Tooltip 或可复制文本。

**Tech Stack:** React、TypeScript、Vite、Ant Design、i18next、Vitest、Testing Library、Playwright。

## Global Constraints

- 用户可见界面统一显示 `WeldonAgent`。
- 内部 `qwenpaw` Python 包、环境变量、CSS prefix、协议 header 和兼容 API 不改名。
- 生产 Web 隐藏版本号、在线更新、GitHub、上游文档、FAQ、Changelog 和发布入口。
- 普通用户不看到宿主盘符、容器路径、内部智能体 ID 或 `default` 标识。
- 前端隐藏不替代后端路径和用户/智能体作用域校验。

## File Structure

- Create: `console/src/config/brand.ts` — 对外品牌常量和可见性策略。
- Create: `console/src/config/brand.test.ts` — 禁止上游品牌和公共维护入口的契约测试。
- Modify: `console/index.html` — 浏览器标题。
- Modify: `console/src/layouts/Header.tsx` — 移除版本、更新检查和上游资源。
- Modify: `console/src/layouts/constants.ts` — 删除不再被生产 UI 消费的公开链接与更新文案。
- Modify: `console/src/layouts/constants.test.ts` — 改为断言生产 UI 无公开上游入口。
- Modify: `console/src/pages/Login/index.tsx` — 登录品牌和无障碍文本。
- Modify: `console/src/pages/Chat/OptionsPanel/defaultConfig.ts` — 聊天标题。
- Modify: `console/src/pages/Chat/index.tsx` — 助手气泡显示名和目录控件调用参数。
- Modify: `console/src/features/project-directory/SessionProjectDirectory.tsx` — 逻辑目录显示模型。
- Modify: `console/src/components/AgentSelector/index.tsx` — 下拉项隐藏 ID。
- Modify: `console/src/locales/zh.json`, `console/src/locales/en.json`, `console/src/locales/ru.json`, `console/src/locales/ja.json`, `console/src/locales/vi.json`, `console/src/locales/id.json`, `console/src/locales/pt-BR.json` — 用户文案。
- Create: `console/src/features/project-directory/SessionProjectDirectory.test.tsx` — 路径隐私测试。
- Modify: `console/src/components/AgentSelector/AgentSelector.test.tsx` — ID 隐私测试。
- Create: `console/src/pages/Chat/branding.test.tsx` — 助手名称测试。
- Create: `e2e/tests/test_branding_and_path_privacy.py` — 浏览器验收。

---

### Task 1: 单一品牌配置源

**Files:**
- Create: `console/src/config/brand.ts`
- Create: `console/src/config/brand.test.ts`
- Modify: `console/index.html`

**Interfaces:**
- Consumes: 无。
- Produces: `PRODUCT_NAME`、`DOCUMENT_TITLE`、`ASSISTANT_NAME`、`PUBLIC_MAINTENANCE_LINKS_ENABLED`、`VERSION_BADGE_ENABLED`。

- [ ] **Step 1: 写品牌契约测试**

```ts
import {
  ASSISTANT_NAME,
  DOCUMENT_TITLE,
  PRODUCT_NAME,
  PUBLIC_MAINTENANCE_LINKS_ENABLED,
  VERSION_BADGE_ENABLED,
} from "./brand";

it("uses the external WeldonAgent identity", () => {
  expect(PRODUCT_NAME).toBe("WeldonAgent");
  expect(ASSISTANT_NAME).toBe("WeldonAgent");
  expect(DOCUMENT_TITLE).toBe("WeldonAgent");
  expect(PUBLIC_MAINTENANCE_LINKS_ENABLED).toBe(false);
  expect(VERSION_BADGE_ENABLED).toBe(false);
});
```

- [ ] **Step 2: 运行测试并确认配置模块尚不存在**

Run: `npm --prefix console test -- --run src/config/brand.test.ts`

Expected: FAIL，模块无法解析。

- [ ] **Step 3: 新增只包含展示语义的品牌配置**

```ts
export const PRODUCT_NAME = "WeldonAgent" as const;
export const DOCUMENT_TITLE = PRODUCT_NAME;
export const ASSISTANT_NAME = PRODUCT_NAME;
export const PUBLIC_MAINTENANCE_LINKS_ENABLED = false as const;
export const VERSION_BADGE_ENABLED = false as const;
```

保持 `theme.prefix: "qwenpaw"`、HTTP header 和本地存储 key 不变，因为它们是内部兼容标识。

- [ ] **Step 4: 将 `console/index.html` 标题改为 `WeldonAgent` 并运行测试**

Run: `npm --prefix console test -- --run src/config/brand.test.ts`

Expected: PASS。

- [ ] **Step 5: 在获得用户单独提交确认后创建品牌配置提交**

```bash
git add console/src/config/brand.ts console/src/config/brand.test.ts console/index.html
git commit -m "feat: 统一 WeldonAgent 外部品牌配置"
```

### Task 2: 页头与登录页移除上游维护入口

**Files:**
- Modify: `console/src/layouts/Header.tsx`
- Modify: `console/src/layouts/constants.ts`
- Modify: `console/src/layouts/constants.test.ts`
- Modify: `console/src/pages/Login/index.tsx`
- Create: `console/src/layouts/Header.test.tsx`
- Create: `console/src/pages/Login/Login.test.tsx`

**Interfaces:**
- Consumes: Task 1 的品牌常量。
- Produces: 无版本请求、无上游链接、无 QwenPaw/CoPaw 文案的页头与登录页。

- [ ] **Step 1: 写页头和登录页面的负向可见性测试**

```tsx
expect(screen.getByText("WeldonAgent")).toBeInTheDocument();
expect(screen.queryByText(/v\d+\.\d+/)).not.toBeInTheDocument();
expect(screen.queryByRole("link", { name: /GitHub|文档|FAQ|Changelog/i })).not.toBeInTheDocument();
expect(screen.queryByText(/QwenPaw|CoPaw/i)).not.toBeInTheDocument();
```

- [ ] **Step 2: 运行定向测试并确认现有页头仍加载版本/资源入口**

Run: `npm --prefix console test -- --run src/layouts/Header.test.tsx src/pages/Login/Login.test.tsx src/layouts/constants.test.ts`

Expected: FAIL，能定位到版本、更新或上游链接。

- [ ] **Step 3: 从 `Header.tsx` 移除版本 API、副作用、更新弹层和资源菜单**

删除版本请求、PyPI 检查、GitHub 按钮、文档/FAQ/Changelog 菜单及相关状态；保留语言、主题、用户菜单等平台功能。页头品牌从 `PRODUCT_NAME` 读取。

- [ ] **Step 4: 清理不再使用的公开链接常量并更新登录品牌**

```tsx
<img src={logo} alt={PRODUCT_NAME} />
```

`constants.ts` 只保留仍被运行界面消费的非上游常量；测试不再断言 GitHub URL。

- [ ] **Step 5: 运行定向测试、类型检查和 lint**

Run: `npm --prefix console test -- --run src/layouts/Header.test.tsx src/pages/Login/Login.test.tsx src/layouts/constants.test.ts`

Run: `npm --prefix console run build`

Expected: PASS；没有未使用导入。

- [ ] **Step 6: 在获得用户单独提交确认后创建页头登录提交**

```bash
git add console/src/layouts/Header.tsx console/src/layouts/constants.ts console/src/layouts/constants.test.ts console/src/pages/Login/index.tsx console/src/layouts/Header.test.tsx console/src/pages/Login/Login.test.tsx
git commit -m "feat: 隐藏外部维护入口并统一登录品牌"
```

### Task 3: 聊天助手名称与用户文案

**Files:**
- Modify: `console/src/pages/Chat/OptionsPanel/defaultConfig.ts`
- Modify: `console/src/pages/Chat/index.tsx:4150-4170`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`
- Modify: `console/src/locales/ru.json`
- Modify: `console/src/locales/ja.json`
- Modify: `console/src/locales/vi.json`
- Modify: `console/src/locales/id.json`
- Modify: `console/src/locales/pt-BR.json`
- Create: `console/src/pages/Chat/branding.test.tsx`

**Interfaces:**
- Consumes: `ASSISTANT_NAME`、`PRODUCT_NAME`。
- Produces: `resolveAssistantDisplayName(externalNick?: string) -> string`，外部渠道自带昵称时保留昵称，否则显示 WeldonAgent。

- [ ] **Step 1: 写助手显示名测试**

```ts
expect(resolveAssistantDisplayName()).toBe("WeldonAgent");
expect(resolveAssistantDisplayName("企业微信机器人")).toBe("企业微信机器人");
```

- [ ] **Step 2: 运行测试并确认当前 fallback 为 `QwenPaw`**

Run: `npm --prefix console test -- --run src/pages/Chat/branding.test.tsx`

Expected: FAIL，当前 `nick: extNick ?? "QwenPaw"`。

- [ ] **Step 3: 实现并使用显示名解析函数**

```ts
export function resolveAssistantDisplayName(externalNick?: string): string {
  return externalNick?.trim() || ASSISTANT_NAME;
}
```

将默认聊天标题改为 `Work with ${PRODUCT_NAME}`；不要修改 `usesQwenPawBackend`、`X-QwenPaw-Chat-Id` 等内部字段。

- [ ] **Step 4: 仅替换用户可见翻译值**

对全部七个 locale 的登录、欢迎、错误页和通知文案做展示值替换；`qwenpawManaged` 等翻译 key 保持原名。运行扫描只检查 JSON value 与生产组件文本，不把源码内部符号误报为展示内容。

- [ ] **Step 5: 运行聊天测试和前端构建**

Run: `npm --prefix console test -- --run src/pages/Chat/branding.test.tsx`

Run: `npm --prefix console run build`

Expected: PASS；构建产物中的可见字符串无 `Work with QwenPaw` 和助手 fallback `QwenPaw`。

- [ ] **Step 6: 在获得用户单独提交确认后创建聊天品牌提交**

```bash
git add console/src/pages/Chat/OptionsPanel/defaultConfig.ts console/src/pages/Chat/index.tsx console/src/pages/Chat/branding.test.tsx console/src/locales/zh.json console/src/locales/en.json console/src/locales/ru.json console/src/locales/ja.json console/src/locales/vi.json console/src/locales/id.json console/src/locales/pt-BR.json
git commit -m "feat: 统一聊天助手与界面文案品牌"
```

### Task 4: 工作目录和内部 ID 展示隐私

**Files:**
- Modify: `console/src/features/project-directory/SessionProjectDirectory.tsx`
- Create: `console/src/features/project-directory/projectDirectoryDisplay.ts`
- Create: `console/src/features/project-directory/SessionProjectDirectory.test.tsx`
- Modify: `console/src/components/AgentSelector/index.tsx`
- Modify: `console/src/components/AgentSelector/AgentSelector.test.tsx`
- Modify: `console/src/pages/Chat/index.tsx:4240-4255`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`
- Modify: `console/src/locales/ru.json`
- Modify: `console/src/locales/ja.json`
- Modify: `console/src/locales/vi.json`
- Modify: `console/src/locales/id.json`
- Modify: `console/src/locales/pt-BR.json`

**Interfaces:**
- Consumes: 当前智能体展示名、目录是否存在、目录来源和管理员权限。
- Produces: `getProjectDirectoryLabel(scope: "agent" | "session", agentDisplayName: string) -> string`；普通视图绝不消费 `project_dir` 作为 title 或正文。

- [ ] **Step 1: 写普通用户看不到物理路径和内部 ID 的测试**

```tsx
renderProjectDirectory({ project_dir: "E:/git_project/QwenPaw/tmp/private", agentName: "QA Agent" });
expect(screen.getByText("QA Agent 工作区")).toBeInTheDocument();
expect(screen.queryByText(/E:\/git_project|\/data\/working/)).not.toBeInTheDocument();
expect(document.body.innerHTML).not.toContain("E:/git_project/QwenPaw/tmp/private");

renderAgentSelector([{ id: "default", name: "默认智能体" }]);
expect(screen.queryByText("ID: default")).not.toBeInTheDocument();
```

- [ ] **Step 2: 运行测试并确认 Tooltip、small 文本和下拉项当前泄露信息**

Run: `npm --prefix console test -- --run src/features/project-directory/SessionProjectDirectory.test.tsx src/components/AgentSelector/AgentSelector.test.tsx`

Expected: FAIL，当前 DOM 包含 `info.project_dir` 和 `ID: ${agent.id}`。

- [ ] **Step 3: 建立逻辑目录展示函数并移除物理路径 Tooltip**

```ts
export function getProjectDirectoryLabel(
  scope: "agent" | "session",
  agentDisplayName: string,
  t: TFunction,
): string {
  return scope === "agent"
    ? t("projectDirectory.logicalAgentWorkspace", { name: agentDisplayName })
    : t("projectDirectory.logicalConversationWorkspace");
}
```

`SessionProjectDirectory` 按钮和 Tooltip 均使用逻辑标签；弹层允许选择逻辑目录来源，不回显宿主/容器绝对路径。受控诊断接口不在本组件中开放。

- [ ] **Step 4: 从智能体选择器移除 ID 行并保持 displayName/状态可辨识**

删除 `<div className={styles.agentOptionId}>`；`value` 仍使用内部 ID，屏幕和辅助技术只读取展示名。

- [ ] **Step 5: 运行测试、类型检查和 DOM 字符串扫描**

Run: `npm --prefix console test -- --run src/features/project-directory/SessionProjectDirectory.test.tsx src/components/AgentSelector/AgentSelector.test.tsx`

Run: `npm --prefix console run build`

Expected: PASS；普通视图 DOM 中不存在测试绝对路径和 `ID: default`。

- [ ] **Step 6: 在获得用户单独提交确认后创建路径隐私提交**

```bash
git add console/src/features/project-directory/SessionProjectDirectory.tsx console/src/features/project-directory/projectDirectoryDisplay.ts console/src/features/project-directory/SessionProjectDirectory.test.tsx console/src/components/AgentSelector/index.tsx console/src/components/AgentSelector/AgentSelector.test.tsx console/src/pages/Chat/index.tsx console/src/locales/zh.json console/src/locales/en.json console/src/locales/ru.json console/src/locales/ja.json console/src/locales/vi.json console/src/locales/id.json console/src/locales/pt-BR.json
git commit -m "feat: 隐藏物理工作目录和内部智能体标识"
```

### Task 5: 浏览器级白标和隐私验收

**Files:**
- Create: `e2e/tests/test_branding_and_path_privacy.py`
- Modify: `docs/deployment-acceptance.md`

**Interfaces:**
- Consumes: Tasks 1-4 和运行中的生产/验收实例。
- Produces: 可重复的页面级验收证据。

- [ ] **Step 1: 编写登录、页头、聊天和工作目录 E2E**

```python
expect(page).to_have_title("WeldonAgent")
expect(page.get_by_text("WeldonAgent").first).to_be_visible()
expect(page.get_by_text(re.compile("QwenPaw|CoPaw", re.I))).to_have_count(0)
expect(page.get_by_role("link", name=re.compile("GitHub|FAQ|Changelog|文档", re.I))).to_have_count(0)
assert not re.search(r"[A-Z]:\\|/data/working|ID: default", page.locator("body").inner_text())
```

- [ ] **Step 2: 在登录页、首次管理员页、普通用户聊天页和文件中心运行 E2E**

Run: `python -m pytest e2e/tests/test_branding_and_path_privacy.py -v`

Expected: PASS；外部可见页面不出现上游品牌、版本、链接、绝对路径和内部默认 ID。

- [ ] **Step 3: 使用浏览器实际切换聊天、文件、设置菜单后复验**

验证返回聊天时仍显示当前智能体展示名；打开目录弹层、文件预览和错误提示，均不泄露物理路径。把页面、角色和结果写入验收文档，不记录真实用户数据。

- [ ] **Step 4: 运行前端全量测试和生产构建**

Run: `npm --prefix console test -- --run`

Run: `npm --prefix console run build`

Expected: PASS。

- [ ] **Step 5: 在获得用户单独提交确认后创建验收提交**

```bash
git add e2e/tests/test_branding_and_path_privacy.py docs/deployment-acceptance.md
git commit -m "test: 覆盖 WeldonAgent 白标与路径隐私"
```
