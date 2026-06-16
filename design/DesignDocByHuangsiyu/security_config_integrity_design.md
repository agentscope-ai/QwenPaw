# QwenPaw 内置工具检测规则完整性保护设计

> **As-built 实现（与当前代码对齐，2026-06）**
>
> 运行时实现已迁至 `extension/rule_integrity/`（verify/repair/routes/startup）及 Console：
> - `console/src/extension/rule_integrity/` — `GlobalRuleIntegrityRepairBanner`（MainLayout 顶栏全局横幅）、`RuleIntegrityPassiveCard`（Integrity Check Tab 内手动「检查」按钮 + findings 表格）、`useRuleIntegrity`
> - 验收：`extension/rule_integrity/tests/test_integration_entry.py::test_rule_integrity_entry_visible`
> - 总交付设计见 `extension/Intergrity  Protection Design.md`
>
> 下文为早期设计稿；若与 as-built 路径或 UI 描述不一致，以 extension 模块与 Console 代码为准。

## 1. 背景

当前 QwenPaw 的工具防护内置规则主要来自：

```text
src/qwenpaw/security/tool_guard/rules/dangerous_shell_commands.yaml
```

例如前端“设置 / 安全 / 工具防护”中看到的 `TOOL_CMD_DANGEROUS_RM`，不是前端硬编码出来的规则，而是后端读取上述 YAML 后通过 API 返回给前端展示。

当前加载链路是：

```text
RuleBasedToolGuardian
  -> load_rules_from_directory()
  -> dangerous_shell_commands.yaml
  -> GuardRule
  -> ToolGuardEngine
  -> /api/config/security/tool-guard/builtin-rules
  -> 前端规则表格
```

目前这个 YAML 文件没有 hash、签名、manifest 或启动校验。如果有人直接删除、修改或弱化其中的规则，后端下一次启动或 reload 时会读取被修改后的内容，前端规则表格也会同步反映被修改后的规则集。

本设计的小目标是：**只保护 `dangerous_shell_commands.yaml` 这个内置规则文件的完整性；发现篡改时先报警，不阻断业务运行。**

## 2. 目标

1. 检测 `dangerous_shell_commands.yaml` 是否被篡改。
2. 检测 `rules_manifest.json` 是否被篡改。
3. 检测签名文件是否缺失或无效。
4. 后端日志中明确报警。
5. 前端“设置 / 安全”页面顶部以醒目红字提示：

```text
内置检测规则已被篡改
```

6. 方案尽量解耦，减少对现有规则加载逻辑的侵入。
7. 第一版只报警，不阻断规则加载。
8. 兼容源码运行、editable install、wheel 安装和后续 exe 打包。

## 3. 非目标

1. 第一版不保护整个 `config.json`。
2. 第一版不保护所有后端安全配置。
3. 第一版不保护用户自定义规则 `custom_rules`。
4. 第一版不改变现有工具防护规则匹配逻辑。
5. 第一版不实现 strict 阻断模式。
6. 第一版不把完整性状态写入 `config.json`。
7. 第一版不试图绝对阻止本机管理员修改程序。目标是提高篡改成本，并做到篡改后可发现。

## 4. 当前代码分析

### 4.1 内置规则文件

当前内置工具规则文件：

```text
src/qwenpaw/security/tool_guard/rules/dangerous_shell_commands.yaml
```

其中包含 `TOOL_CMD_DANGEROUS_RM` 等规则：

```yaml
- id: TOOL_CMD_DANGEROUS_RM
  tools: [execute_shell_command]
  params: [command]
  category: command_injection
  severity: HIGH
  patterns:
    - "\\brm\\b"
    - "\\bdel\\b"
    - "\\bRemove-Item\\b"
```

如果整条规则从 YAML 中删除，后端不会再加载它，前端规则表也不会再显示它。

### 4.2 后端规则加载位置

规则加载代码在：

```text
src/qwenpaw/security/tool_guard/guardians/rule_guardian.py
```

关键逻辑：

```python
_DEFAULT_RULES_DIR = Path(__file__).resolve().parent.parent / "rules"

_DEFAULT_RULE_FILES: list[str] = [
    "dangerous_shell_commands.yaml",
]
```

默认加载逻辑：

```python
def load_rules_from_directory(
    rules_dir: Path | None = None,
    *,
    rule_files: list[str] | None = None,
) -> list[GuardRule]:
    directory = rules_dir or _DEFAULT_RULES_DIR
    ...
    else:
        yaml_files = [directory / f for f in _DEFAULT_RULE_FILES]

    rules: list[GuardRule] = []
    for yaml_file in yaml_files:
        if yaml_file.is_file():
            rules.extend(load_rules_from_yaml(yaml_file))
```

### 4.3 前端规则展示来源

前端调用：

```text
GET /api/config/security/tool-guard/builtin-rules
```

后端接口在：

```text
src/qwenpaw/app/routers/config.py
```

它也是直接调用：

```python
rules = load_rules_from_directory()
```

因此，前端看到的内置规则列表和后端实际加载的内置规则，都依赖同一个 YAML 文件。

### 4.4 package data

当前 `pyproject.toml` 已包含：

```toml
"qwenpaw" = [
    "security/tool_guard/rules/**",
]
```

所以如果把 manifest 和签名文件放到 `security/tool_guard/rules/` 目录下，后续打包 wheel 或 exe 时可以作为 package data 一起带上。

## 5. 威胁模型

### 5.1 能防什么

本方案可以发现：

1. 只修改 `dangerous_shell_commands.yaml`。
2. 删除 `TOOL_CMD_DANGEROUS_RM` 等关键规则。
3. 修改规则正则，使检测变弱。
4. 修改规则 severity。
5. 修改 manifest 但没有合法签名。
6. 删除 manifest 或签名文件。
7. 发布包中文件被非预期改动。

### 5.2 不能绝对防什么

如果使用者拥有本机管理员权限，且 Python 源码明文发布，他可以同时修改：

```text
dangerous_shell_commands.yaml
rules_integrity.py
rule_guardian.py
```

这种情况下，任何运行在同一份本地代码里的校验逻辑都不能提供绝对防护。

因此，本方案的安全目标是：

```text
防误改
防低成本静默篡改
让只改规则文件或 manifest 的篡改可发现
为后续 exe 签名和 strict 模式打基础
```

## 6. 总体方案

采用“官方签名 manifest + 文件 hash”模式。

新增三个核心部分：

```text
src/qwenpaw/security/tool_guard/rules/rules_manifest.json
src/qwenpaw/security/tool_guard/rules/rules_manifest.sig
src/qwenpaw/security/tool_guard/rules_integrity.py
```

同时新增生成脚本：

```text
scripts/update_tool_rule_manifest.py
```

运行时流程：

```text
1. 后端准备加载内置规则
2. 调用 rules_integrity.py
3. 使用代码内置公钥验证 rules_manifest.sig
4. 确认 rules_manifest.json 未被篡改
5. 从 manifest 读取 dangerous_shell_commands.yaml 的 expected sha256
6. 读取当前 YAML 文件 bytes，先做 LF 归一化（`\r\n` 和 lone `\r` → `\n`），再计算 actual sha256
7. 对比 expected 和 actual
8. 如果不一致，写日志并更新内存状态
9. 继续加载 YAML
10. 前端通过状态 API 读取完整性状态
11. 如果状态异常，在“设置 / 安全”顶部显示红色告警
```

## 7. 解耦与低侵入设计

为了减少侵入式修改，设计上遵循以下原则：

1. `rule_guardian.py` 只增加一个薄集成调用。
2. 完整性校验逻辑独立放在 `rules_integrity.py`。
3. 前端不解析文件、不计算 hash、不判断篡改，只读取后端状态。
4. 不修改 `ToolGuardConfig`。
5. 不写入 `config.json`。
6. 不改变 `load_rules_from_directory()` 的返回类型。
7. 不影响传入自定义 `rules_dir` 的测试和扩展场景。
8. 校验失败不抛异常，第一版只报警。

建议后端集成点只保留类似：

```python
if rules_dir is None:
    verify_builtin_rule_files(directory, _DEFAULT_RULE_FILES)
```

这样 `RuleBasedToolGuardian` 仍然只负责加载和匹配规则，完整性检查作为旁路能力存在。

## 8. 文件布局

建议新增：

```text
src/qwenpaw/security/tool_guard/rules/
  dangerous_shell_commands.yaml
  rules_manifest.json
  rules_manifest.sig

src/qwenpaw/security/tool_guard/
  rules_integrity.py

scripts/
  update_tool_rule_manifest.py
```

其中：

```text
dangerous_shell_commands.yaml
```

是被保护对象。

```text
rules_manifest.json
```

记录官方发布时该 YAML 的 SHA-256（LF 归一化后的语义内容 digest，不是 raw 磁盘 bytes）。

```text
rules_manifest.sig
```

是开发者私钥对 manifest 的 Ed25519 签名。

```text
rules_integrity.py
```

负责运行时验证 manifest 签名和 LF 归一化后的 YAML hash。

```text
update_tool_rule_manifest.py
```

负责开发/发布时重新生成 manifest 和签名。

## 9. Manifest 设计

`rules_manifest.json` 建议格式：

```json
{
  "files": {
    "dangerous_shell_commands.yaml": {
      "required": true,
      "sha256": "<hex>"
    }
  },
  "generated_at": "2026-06-07T00:00:00Z",
  "hash_scheme": "sha256",
  "schema_version": 1,
  "signature_scheme": "ed25519-v1"
}
```

为保证签名稳定，生成脚本输出 manifest 时使用 canonical JSON：

```python
json.dumps(
    data,
    sort_keys=True,
    ensure_ascii=False,
    separators=(",", ":"),
)
```

签名对象是 `rules_manifest.json` 的原始 UTF-8 bytes。

## 10. 签名设计

使用 Ed25519 非对称签名。

原因：

1. 项目已有 `cryptography>=43.0.0` 依赖。
2. Ed25519 签名短，验证快，使用简单。
3. 私钥不需要进入用户机器。
4. 运行时只需要内置公钥。

密钥放置：

```text
私钥：只保存在发布机器或 CI 的安全环境中，不进仓库
公钥：写入 rules_integrity.py 或独立 rules_public_key.py
```

开发或发布时：

```text
QWENPAW_RULE_SIGNING_PRIVATE_KEY_FILE=/secure/path/ed25519_private.pem
python scripts/update_tool_rule_manifest.py
```

## 11. 后端校验模块设计

新增：

```text
src/qwenpaw/security/tool_guard/rules_integrity.py
```

行尾归一化语义：

```text
read bytes -> replace CRLF and lone CR with LF -> SHA-256 hex
```

共享 helper `_sha256_normalized_content(bytes) -> hex` 必须被 runtime verify、repair download validation、`scripts/update_tool_rule_manifest.py` 复用。只做行尾归一化，不做 YAML 重序列化，不裁剪 trailing spaces。

建议对外暴露：

```python
def verify_builtin_rule_files(
    rules_dir: Path,
    rule_files: list[str],
) -> RuleIntegrityResult:
    ...


def get_last_rule_integrity_status() -> RuleIntegrityResult:
    ...
```

建议数据结构：

```python
@dataclass
class RuleIntegrityFinding:
    file: str
    reason: str
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    detail: str = ""


@dataclass
class RuleIntegrityResult:
    ok: bool
    status: str
    message: str
    checked_at: str | None
    findings: list[RuleIntegrityFinding]
```

状态枚举：

```text
unknown
ok
tampered
manifest_invalid
missing_manifest
missing_signature
check_failed
```

模块内部维护最近一次校验状态：

```python
_last_status: RuleIntegrityResult | None = None
```

`verify_builtin_rule_files()` 每次执行后更新 `_last_status`。

`get_last_rule_integrity_status()` 只读取 `_last_status`，不重新读文件、不重复打印日志。

## 12. 后端集成点

### 12.1 规则加载前校验

修改：

```text
src/qwenpaw/security/tool_guard/guardians/rule_guardian.py
```

只在默认内置规则路径启用校验：

```python
if rules_dir is None:
    verify_builtin_rule_files(directory, _DEFAULT_RULE_FILES)
```

不对自定义 `rules_dir` 强制校验。

原因：

1. 单元测试常用临时 `rules_dir`。
2. 自定义规则目录不属于官方内置规则。
3. 避免把完整性保护逻辑扩散到扩展场景。

### 12.2 状态 API

新增只读接口：

```text
GET /api/config/security/tool-guard/rules-integrity
```

位置：

```text
src/qwenpaw/app/routers/config.py
```

放在工具防护相关 API 附近。

该接口：

1. 不触发重新校验。
2. 不读取 YAML。
3. 只返回最近一次校验状态。
4. 如果还没校验过，返回 `unknown`。

响应示例：

```json
{
  "status": "tampered",
  "ok": false,
  "message": "内置检测规则已被篡改",
  "checked_at": "2026-06-07T00:00:00Z",
  "findings": [
    {
      "file": "dangerous_shell_commands.yaml",
      "reason": "sha256_mismatch",
      "expected_sha256": "expected...",
      "actual_sha256": "actual...",
      "detail": ""
    }
  ]
}
```

## 13. 前端告警设计

### 13.1 展示位置

前端需要在“设置 / 安全”页面顶部显示红色告警。

建议位置：

```text
console/src/pages/Settings/Security/index.tsx
```

放在：

```text
PageHeader 下方
Tabs 上方
```

这样用户不管当前打开的是“工具防护”“文件防护”“Skill 扫描”还是“免认证主机”，都能看到告警。

### 13.2 展示文案

主文案：

```text
内置检测规则已被篡改
```

辅助文案：

```text
请检查 dangerous_shell_commands.yaml、rules_manifest.json 和 rules_manifest.sig 是否来自官方发布包。
```

### 13.3 样式

建议样式：

```text
红色文字
浅红背景
红色边框
页面顶部
较高视觉权重
```

对应样式文件：

```text
console/src/pages/Settings/Security/index.module.less
```

可以新增：

```less
.integrityAlert {
  margin: 12px 16px 0;
  padding: 12px 14px;
  border: 1px solid #ff4d4f;
  background: #fff1f0;
  color: #cf1322;
  border-radius: 8px;
  font-weight: 600;
}
```

暗色模式下可补充对应样式。

### 13.4 前端数据流

修改：

```text
console/src/api/modules/security.ts
```

新增：

```typescript
getToolGuardRulesIntegrity: () =>
  request<ToolGuardRulesIntegrityResponse>(
    "/config/security/tool-guard/rules-integrity",
  )
```

修改：

```text
console/src/pages/Settings/Security/useSecurityPage.ts
```

在安全页加载时请求完整性状态，并返回给页面：

```typescript
rulesIntegrity
```

修改：

```text
console/src/pages/Settings/Security/index.tsx
```

当：

```typescript
rulesIntegrity?.ok === false
```

渲染红色告警。

前端不要自行计算 hash，也不要根据规则列表是否缺失来判断篡改。

## 14. 运行时流程

```mermaid
flowchart TD
    startNode["QwenPaw backend starts"] --> createEngine["Create ToolGuardEngine"]
    createEngine --> createGuardian["Create RuleBasedToolGuardian"]
    createGuardian --> verifyRules["Verify built-in rules integrity"]
    verifyRules --> integrityOk{"Integrity OK"}
    integrityOk -->|"Yes"| loadYaml["Load dangerous_shell_commands.yaml"]
    integrityOk -->|"No"| cacheBadStatus["Cache tampered status and log warning"]
    cacheBadStatus --> loadYaml
    loadYaml --> serveApi["Serve builtin-rules and guard tool calls"]
    securityPage["Settings Security Page"] --> statusApi["GET rules-integrity"]
    statusApi --> showAlert{"ok false"}
    showAlert -->|"Yes"| redAlert["Show red alert"]
    showAlert -->|"No"| noAlert["No tamper alert"]
```

## 15. 校验失败策略

当前实现（always-on fail-closed，无用户开关）：

```text
fail_closed + auto_repair
```

行为：

1. 后端写 warning/error 日志。
2. 更新最近一次完整性状态。
3. **不加载**被篡改的内置 YAML 规则（内置规则集视为禁用）。
4. **阻断所有工具调用**，直至完整性恢复。
5. 前端**全局顶栏**（MainLayout，`GlobalRuleIntegrityRepairBanner`）显示红色告警：「安全配置文件被篡改，所有规则已被禁用，正在修复中」。
6. 后端后台任务自动从可信源修复；修复成功后显示绿色「已自动修复完成」横幅（短暂），随后界面恢复正常。**同一篡改周期内用户必须先看到红色横幅再看到绿色**（即使进入安全页时修复已完成，也先红至少 5 秒再绿）；后端通过 `tamper_banner_cycle_active` 标记该周期。
7. 若从 GitHub 拉取修复内容时发生**连接超时**（`httpx.TimeoutException`），前端红色横幅切换为「连接超时，正在重试修复第 x/5 次」（x 为当前已连续超时次数，1–5）；同一 lockdown 周期内连续 5 次超时后**暂时放弃自动修复**（`auto_repair_abandoned=true`），横幅显示已放弃；工具仍保持封禁。**放弃后**仍可通过 **300s watchdog** 或 **POST rules-integrity/repair** 手动 API 再次触发修复（重置放弃状态并重新走 5 次超时重试）。
8. `status=unknown`（尚未完成首次校验）不阻断工具。
9. 自定义 `rules_dir`（仅测试/代码注入）不在保护范围内。

legacy 第一版 `warn only` 已废弃。

## 16. 日志设计

YAML hash 不一致：

```text
Built-in tool guard rule integrity check failed: dangerous_shell_commands.yaml
reason=sha256_mismatch
expected=<manifest hash>
actual=<actual hash>
hash_basis=lf_normalized_content
action=warn_only_loaded_anyway
```

仅 CRLF/LF 差异、语义内容未变时，不得产生上述 `sha256_mismatch` 日志。

manifest 签名失败：

```text
Built-in tool guard rule manifest signature verification failed
reason=signature_invalid
action=warn_only_loaded_anyway
```

manifest 缺失：

```text
Built-in tool guard rule manifest missing
reason=missing_manifest
action=warn_only_loaded_anyway
```

签名文件缺失：

```text
Built-in tool guard rule manifest signature missing
reason=missing_signature
action=warn_only_loaded_anyway
```

为避免周期检测时日志刷屏，实际实现中对失败日志做去重：

```text
同一种 status + finding 指纹重复出现时，只记录第一次
恢复为 ok 后清空失败指纹
下一次新的篡改内容会再次报警
```

## 17. Manifest 生成脚本设计

新增：

```text
scripts/update_tool_rule_manifest.py
```

职责：

1. 定位 `src/qwenpaw/security/tool_guard/rules/dangerous_shell_commands.yaml`。
2. 通过 `_sha256_normalized_content()` 计算 LF 归一化 SHA-256。
3. 生成 canonical `rules_manifest.json`。
4. 读取 Ed25519 私钥。
5. 对 manifest bytes 签名。
6. 写出 `rules_manifest.sig`。

输入：

```text
QWENPAW_RULE_SIGNING_PRIVATE_KEY_FILE
```

输出：

```text
src/qwenpaw/security/tool_guard/rules/rules_manifest.json
src/qwenpaw/security/tool_guard/rules/rules_manifest.sig
```

发布流程要求：

```text
只要修改 dangerous_shell_commands.yaml，就必须重新生成 manifest 和签名。
```

## 18. 周期检测与前端自动刷新

### 18.1 后端 5 秒周期校验

除启动和规则加载时触发校验外，实际实现还在 FastAPI lifespan 中新增了后台周期任务。

位置：

```text
src/qwenpaw/app/_app.py
```

行为：

```text
后端启动后立即校验一次
之后每 5 秒校验一次
服务关闭时取消后台任务
```

周期任务调用：

```text
verify_default_builtin_rule_files()
```

该函数位于：

```text
src/qwenpaw/security/tool_guard/rules_integrity.py
```

性能评估：

```text
dangerous_shell_commands.yaml 只有几百行
每次检测只读取 manifest、signature 和 YAML
执行一次 sha256 和 Ed25519 verify
5 秒一次对本地 CPU 和磁盘压力可以忽略
```

### 18.2 前端 5 秒轮询

前端“设置 / 安全”页面打开期间，每 5 秒请求一次：

```text
GET /api/config/security/tool-guard/rules-integrity
```

位置：

```text
console/src/pages/Settings/Security/useToolGuard.ts
```

行为：

```text
页面加载时读取一次完整性状态
页面打开期间每 5 秒轮询一次
请求失败时只打印 console.warn，不阻塞安全页主体展示
```

实际发现链路：

```text
后端最多 5 秒发现规则文件篡改
前端最多再 5 秒拉到最新状态
最坏约 10 秒内显示红色告警
```

### 18.3 告警恢复

当 `dangerous_shell_commands.yaml` 被恢复到与 manifest 匹配的内容后：

```text
后端下一轮 5 秒校验会把状态恢复为 ok
前端下一轮 5 秒轮询会拿到 ok
红色告警自动消失
```

## 19. 前端一键修复

### 19.1 目标

当完整性检测发现 `dangerous_shell_commands.yaml` 被篡改时，前端除了显示红色告警，还提供一个“修复”按钮。

用户点击“修复”后：

```text
前端只发起请求
后端负责下载、校验、备份、原子替换和重新校验
```

前端不直接下载文件，也不直接写本地文件。

### 19.2 固定可信恢复源

恢复源固定为用户指定的 GitHub 基线仓库和 commit：

```text
仓库：https://github.com/axjlpl2026-commits/QwenPaw
commit：058c52847faeb98fc0dea6ef56ac6d4a80f5e907
```

主恢复 URL：

```text
https://raw.githubusercontent.com/axjlpl2026-commits/QwenPaw/058c52847faeb98fc0dea6ef56ac6d4a80f5e907/src/qwenpaw/security/tool_guard/rules/dangerous_shell_commands.yaml
```

兜底恢复 URL：

```text
https://api.github.com/repos/axjlpl2026-commits/QwenPaw/contents/src/qwenpaw/security/tool_guard/rules/dangerous_shell_commands.yaml?ref=058c52847faeb98fc0dea6ef56ac6d4a80f5e907
```

使用固定 commit 而不是 branch/tag，可以避免分支漂移或 tag 被移动带来的恢复源不确定性。
两个 URL 都来自 GitHub 官方源，并且都固定到同一个 commit。后端无论从哪个 URL 下载成功，都必须再用本地 signed manifest 中的 SHA-256 校验内容。

### 19.3 后端修复 API

新增：

```text
POST /api/config/security/tool-guard/rules-integrity/repair
```

职责：

```text
1. 验证本地 rules_manifest.sig 有效
2. 优先从 GitHub raw 固定 URL 下载 dangerous_shell_commands.yaml
3. 如果 raw 由于 TLS 握手超时、连接断开等网络问题失败，则从 GitHub Contents API 固定 URL 兜底下载
4. 用本地 manifest 校验下载内容的 LF 归一化 sha256
5. 校验通过后备份当前本地 dangerous_shell_commands.yaml
6. 原子替换本地 dangerous_shell_commands.yaml
7. 重新运行 verify_default_builtin_rule_files()
8. 返回修复结果和最新完整性状态
```

如果本地 `rules_manifest.json` 或 `rules_manifest.sig` 无效，则拒绝自动修复。原因是此时后端无法判断下载到的 YAML 是否符合当前发布包信任基线。

### 19.4 备份策略

替换前备份本地文件到同目录：

```text
dangerous_shell_commands.yaml.repair-backup.<UTC timestamp>
```

备份只用于人工回滚，不参与信任判断。

### 19.5 原子替换

后端下载并校验通过后，不直接覆盖目标文件，而是：

```text
1. 写入临时文件 dangerous_shell_commands.yaml.tmp.<random>
2. fsync/关闭文件
3. os.replace(tmp, dangerous_shell_commands.yaml)
```

这样避免写入中断导致规则文件半写入。

### 19.6 前端交互

红色告警区域增加“修复”按钮。

点击后：

```text
1. 按钮进入 loading
2. 调用 POST /api/config/security/tool-guard/rules-integrity/repair
3. 成功后刷新 rules-integrity 状态
4. 如果 ok=true，红色告警自动消失
5. 如果失败，展示错误消息，保留红色告警
```

### 19.7 网络与证书

恢复下载使用项目已有的 `httpx`，不使用 `urllib.request`。

原因：

```text
Windows 环境下系统 Python urllib 可能遇到本地证书链问题
httpx 使用项目已有依赖，行为和现有 CLI HTTP 逻辑更一致
```

实际实现：

```text
1. 设置明确的 User-Agent
2. connect timeout 拉长到 60 秒
3. 每个 GitHub 官方源最多重试 2 次
4. raw.githubusercontent.com 失败后自动尝试 api.github.com contents
5. API 返回的 base64 内容解码后仍必须通过 manifest sha256 校验
```

如果下载失败、超时、HTTP 非 200、TLS 失败，修复 API 返回失败，不修改本地文件。

## 20. exe 打包兼容性

这套方案兼容 exe。

### 20.1 onedir

可能形态：

```text
QwenPaw/
  qwenpaw.exe
  _internal/
    qwenpaw/security/tool_guard/rules/
      dangerous_shell_commands.yaml
      rules_manifest.json
      rules_manifest.sig
```

运行时读取这些 package data 并校验。

### 20.2 onefile

可能形态：

```text
qwenpaw.exe
```

PyInstaller 运行时会把资源解压到临时目录。只要这三个文件被作为 package data 打包进去，运行时仍能读取并校验。

### 20.3 exe 签名

后续正式发布建议：

1. `rules_manifest.sig` 保护 manifest。
2. manifest hash 保护 YAML。
3. Windows Authenticode 保护 exe 本体。

这样：

```text
只改 YAML -> hash 校验失败
改 YAML 和 manifest -> manifest 签名失败
改 exe 校验逻辑 -> exe 代码签名失效
```

## 21. 测试计划

### 21.1 后端单元测试

测试文件建议：

```text
tests/unit/security/tool_guard/test_rules_integrity.py
```

测试场景：

1. 正常 manifest + 正常 YAML，返回 `ok=True`。
2. 修改 YAML 不更新 manifest，返回 `ok=False`，status 为 `tampered`。
3. 修改 manifest 不更新 sig，返回 `ok=False`，status 为 `manifest_invalid`。
4. 删除 manifest，返回 `ok=False`，status 为 `missing_manifest`。
5. 删除 sig，返回 `ok=False`，status 为 `missing_signature`。
6. manifest 中缺少 required 文件，返回异常状态。
7. hash 算法不支持，返回异常状态。
8. 校验失败时不抛异常。
9. `get_last_rule_integrity_status()` 返回最近一次结果。
10. 冻结 explicit entrypoint `sec-e2e-029`：LF-canonical 与 CRLF-only 分支均 `ok=true`；语义篡改仍 `tampered`。
11. helper contract：`test_sha256_normalized_content_shared_helper_contract` 证明 runtime 与 manifest script 共享 `_sha256_normalized_content`。

### 21.2 规则加载测试

现有测试位置：

```text
tests/unit/security/tool_guard/guardians/test_rule_guardian.py
```

新增或调整：

1. 默认内置规则路径会调用完整性校验。
2. 自定义 `rules_dir` 不强制官方签名。
3. 校验失败后仍继续加载规则。

### 21.3 API 测试

测试：

```text
GET /api/config/security/tool-guard/rules-integrity
```

场景：

1. 正常状态返回 `ok: true`。
2. 篡改状态返回 `ok: false`。
3. 篡改状态返回文案 `内置检测规则已被篡改`。
4. 未校验过返回 `unknown`。

### 21.4 前端测试

测试：

1. `rulesIntegrity.ok === false` 时显示红色告警。
2. 告警文案包含 `内置检测规则已被篡改`。
3. `rulesIntegrity.ok === true` 时不显示告警。
4. `rulesIntegrity.status === "unknown"` 时不显示篡改告警。
5. 后端接口失败时不阻塞安全页主体展示。
6. 页面打开期间 5 秒轮询一次完整性状态。
7. 篡改状态下显示“修复”按钮。
8. 点击修复成功后刷新完整性状态并清除告警。
9. 点击修复失败时保留告警并展示错误。

### 21.5 修复 API 测试

测试：

```text
POST /api/config/security/tool-guard/rules-integrity/repair
```

场景：

1. 本地 YAML 被篡改，远端下载内容 hash 匹配 manifest，修复成功。
2. 本地 manifest 签名无效，拒绝修复。
3. 远端下载失败，拒绝修复且不修改本地文件。
4. 远端内容 hash 不匹配 manifest，拒绝修复且不修改本地文件。
5. 替换前创建备份文件。
6. 替换后重新校验返回 `ok: true`。

### 21.6 已执行验证

当前实现已执行过以下验证：

```text
后端完整性校验：ok
Python 编译检查：通过
规则守卫单元测试：64 passed, 6 skipped
前端 npm run build：通过
编辑文件 lint：无错误
```

一键修复基线重建：

```text
基线 commit：058c52847faeb98fc0dea6ef56ac6d4a80f5e907
dangerous_shell_commands.yaml sha256：138904e36b497e300ab93722db569f454c55a02ae1d08726034603695b4624f8
manifest public_key_hex：db31cea4a9fc8fd92d1e34a095d33699848f52bc5695f0768d697963e3966a7e
verify_default_builtin_rule_files()：ok
```

手工篡改/恢复验证：

```text
1. 备份 dangerous_shell_commands.yaml 为 dangerous_shell_commands.yaml.bak
2. 在 dangerous_shell_commands.yaml 末尾追加注释，制造 sha256_mismatch
3. 后端日志检测到 status=tampered
4. rules-integrity API 返回 ok=false, status=tampered
5. 前端安全页显示红色告警：内置检测规则已被篡改
6. 删除篡改注释恢复原文件
7. 后端下一轮检测恢复 ok=true
8. 前端下一轮轮询后红色告警消失
```

## 22. 实施步骤

### Phase 1：后端校验模块

1. 新增 `rules_integrity.py`。
2. 定义结果模型。
3. 实现 manifest 读取。
4. 实现 Ed25519 签名验证。
5. 实现 YAML SHA-256 校验。
6. 实现最近状态缓存。
7. 校验失败只日志报警，不抛异常。

### Phase 2：生成 manifest 和签名

1. 新增 `scripts/update_tool_rule_manifest.py`。
2. 生成 `rules_manifest.json`。
3. 生成 `rules_manifest.sig`。
4. 将两个文件放入 `rules/` 目录。

### Phase 3：接入规则加载

1. 在 `load_rules_from_directory()` 默认内置规则路径前调用校验。
2. 自定义 `rules_dir` 不校验。
3. 保持原返回类型和加载行为。

### Phase 4：后端状态 API

1. 新增 `GET /api/config/security/tool-guard/rules-integrity`。
2. 返回最近一次状态。
3. 未校验时返回 `unknown`。

### Phase 5：后端周期检测

1. 在 FastAPI lifespan 中创建后台任务。
2. 每 5 秒调用一次 `verify_default_builtin_rule_files()`。
3. 服务关闭时取消后台任务。
4. 对重复失败日志去重，避免刷屏。

### Phase 6：前端红色告警与轮询

1. `security.ts` 新增 API 类型和调用。
2. `useSecurityPage.ts` 加载完整性状态。
3. `index.tsx` 在 `PageHeader` 下方展示红色告警。
4. `index.module.less` 新增样式。
5. `useToolGuard.ts` 每 5 秒轮询一次完整性状态。

### Phase 7：前端修复按钮与后端修复 API

1. 在 `rules_integrity.py` 中新增固定官方源 URL 和修复函数。
2. 修复函数先验证本地 manifest 签名。
3. 使用 `httpx` 下载固定 commit 上的 YAML。
4. 用本地 manifest 校验下载 YAML hash。
5. 备份本地被篡改文件。
6. 原子替换目标 YAML。
7. 重新运行完整性校验并返回状态。
8. 在 `config.py` 中新增 repair API。
9. 前端告警区域增加“修复”按钮。

### Phase 8：测试

1. 后端单元测试。
2. 路由测试。
3. 前端组件或 hook 测试。
4. 手工验证：改 YAML 后刷新安全页，看到红字。
5. 手工验证：点击修复后红字自动消失。

## 23. 后续增强方向

1. 增加 strict 模式。
2. 把更多内置规则文件纳入 manifest。
3. 把完整性事件写入安全审计日志。
4. 在首页或状态栏展示安全异常。
5. exe 发布时增加 Authenticode 签名。
6. 在 CI 中强制检查：修改 YAML 后必须同步更新 manifest 和签名。
7. 发布页面提供官方 checksum，方便外部独立验证。
8. 如果未来需要更实时，可从轮询升级为 WebSocket 或 SSE 推送。
9. 将固定恢复源 URL 做成发布时生成的常量，随版本升级更新。

## 24. 最终结论

推荐采用：

```text
Ed25519 签名 manifest
+ dangerous_shell_commands.yaml LF 归一化 SHA-256
+ 后端低侵入校验模块（LF/CRLF 等价语义内容通过）
+ 后端 5 秒周期检测
+ 后端状态 API
+ 前端设置/安全页 5 秒轮询
+ 前端红色告警
+ 前端修复按钮
+ 后端固定 commit 可信源恢复
```

该方案的优点：

1. 对现有规则加载逻辑侵入小。
2. 不污染 `config.json`。
3. 不改变工具防护行为。
4. 能发现只篡改 YAML 或 manifest 的情况。
5. 前端能给用户明确安全提示。
6. 篡改后最坏约 10 秒内在安全页显示告警。
7. 恢复文件后最坏约 10 秒内自动清除告警。
8. 用户可以在安全页一键修复被篡改的内置规则文件。
9. 后续可平滑升级到 strict 模式和 exe 代码签名。

