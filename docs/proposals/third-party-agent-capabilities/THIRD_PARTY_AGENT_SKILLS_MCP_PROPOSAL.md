# 第三方 Agent 接入 QwenPaw Skills 与 MCP 方案

状态：Approved / Implementation
范围：Codex、Qoder，以及后续所有第三方 Harness

## 1. 已确认的产品边界

QwenPaw 继续作为 Skills 与 MCP 的统一控制面，但不建设 MCP
Gateway。QwenPaw 在启动第三方 Harness 会话时，把当前智能体的有效
Skills/MCP 直接转换成 Provider 原生配置。

这是一条单向投影链路：

```text
QwenPaw Skills / MCP
          |
          | resolve + project at runtime
          v
Codex / Qoder / future Harness session
```

- QwenPaw 管理的能力只注入由 QwenPaw 启动的 Provider 进程。
- 不修改 `~/.codex/config.toml`、`~/.qoder` 等用户全局配置。
- 用户单独打开 Codex/Qoder 时，不会看到 QwenPaw 注入的配置。
- 同一份 QwenPaw 配置可以投影给多个支持该能力的 Harness。
- Provider 自有配置可以被 QwenPaw 发现和展示，但默认只读且仅属于该
  Provider。
- 第三方 Harness 的原生限制是已接受的产品边界，不追求与 QwenPaw
  Driver 运行时完全等价。

## 2. 控制面语义

MCP 页面按来源分组：

```text
QwenPaw 管理
  GitHub        已启用    Codex / Qoder
  Context7      已启用    Codex / Qoder

Codex 本地配置
  Figma         已启用    仅 Codex       [导入到 QwenPaw]

Qoder 本地配置
  Internal      已启用    仅 Qoder
```

第一期范围：

- QwenPaw MCP 可编辑，并运行时投影给第三方 Harness。
- Provider 自有 MCP 自动发现、只读展示。
- 不做自动双向同步。
- “导入到 QwenPaw”只保留产品入口设计，不在第一期实现凭据迁移。

Provider 自有 OAuth、环境变量和 Plugin MCP 不能安全自动迁移，因此即使
未来实现导入，也必须由用户显式操作。

## 3. 公共能力层

公共层放在 `qwenpaw/harnesses/capabilities/`，不得在业务入口按
`codex`、`qoder` 写条件分支。

```python
class HarnessSkillDefinition(BaseModel):
    name: str
    description: str
    directory: Path


class HarnessMCPServerDefinition(BaseModel):
    name: str
    transport: Literal["stdio", "streamable_http", "sse"]
    command: str | None
    args: list[str]
    cwd: Path | None
    url: str | None
    env: dict[str, str]
    headers: dict[str, str]
    enabled_tools: list[str]


class HarnessRuntimeCapabilities(BaseModel):
    skills: list[HarnessSkillDefinition]
    mcp_servers: list[HarnessMCPServerDefinition]
```

`HarnessCapabilityResolver` 的职责：

1. 根据 workspace 和 request context 解析当前频道有效的 Skills。
2. 从现有 DriverCard/CredentialStore 解析启用的 MCP Server。
3. 在进入 Adapter 前过滤 channel/user/source policy 能确定的范围。
4. 返回仅存在于内存中的运行时能力。
5. 不把明文密钥写入 agent.json、session 文件或日志。

能力在 Provider client/thread 创建时解析。配置变化对新会话生效；第一期
不热更新活动会话。

## 4. Skills 直接投影

### Codex

使用已验证的 Codex app-server 方法：

```text
skills/extraRoots/set
```

将 `resolve_effective_skills()` 得到的 Skill 目录直接作为 extra roots，
不复制文件，不写入 `.agents/skills`。

该设置属于 app-server 而非 thread。为避免不同频道的 Skill 集合串扰，
Codex client 必须按运行时能力 fingerprint 隔离；相同 fingerprint 可以
复用进程。

### Qoder

Qoder 的 `skills` 参数只控制允许调用的名称，不能指定任意发现目录。
因此为每个能力 fingerprint 生成 QwenPaw 管理的本地 Plugin：

```text
<workspace>/.qwenpaw/harness/qoder/skills/<fingerprint>/
  .qoder-plugin/plugin.json
  skills/
    <name>/SKILL.md
```

- 使用文件复制而非目录软链接，兼容 Windows。
- 通过 Qoder SDK `plugins` 注入。
- 通过 `skills` 设置明确 allowlist。
- 不写入工作区根目录 `.qoder/skills`。

## 5. MCP 直接投影

### QwenPaw 管理的 MCP

公共 Resolver 将 MCP DriverCard 转成统一运行时定义，Adapter 再转换成
Provider 原生配置：

- Codex：在启动 app-server 时通过 session/config override 注入
  `mcp_servers`。
- Qoder：通过 `QoderAgentOptions.mcp_servers` 注入。
- Future Harness：实现自己的 `HarnessMCPProjector`。

秘密只注入 Provider 子进程的环境或启动期配置，不写 Provider 全局配置。

### Provider 自有 MCP

- Codex 使用 `codex mcp list --json` 读取当前 workspace 下的有效配置。
- Qoder 使用其 SDK/CLI 可用的配置查询能力；若没有稳定机器可读接口，
  Provider 声明 `mcp_discovery=False`，不做文件格式猜测。
- 发现结果通过统一 DTO 返回前端。
- Provider 自有 MCP 不会自动投影到其他 Harness。

### 已接受的限制

- 实际 MCP client 是 Codex/Qoder，不经过 QwenPaw DriverManager。
- DriverPolicy 只能在会话创建时转换成 Server/tool allowlist；无法保证
  每个 Provider 都支持完整的 channel/user/source 动态策略。
- Provider 子进程会在内存中接触 MCP 凭据。
- OAuth 刷新遵循 Provider 能力，必要时需要新会话或重启 client。
- Provider 不支持 tool allowlist 时，UI 必须显示能力降级，不能暗示策略
  已完整生效。

## 6. Provider-neutral 接口

```python
class HarnessCapabilityProjector(Protocol):
    async def prepare(
        self,
        capabilities: HarnessRuntimeCapabilities,
    ) -> HarnessProjection: ...


class HarnessMCPDiscovery(Protocol):
    async def list_provider_servers(
        self,
        cwd: Path,
    ) -> list[HarnessDiscoveredMCPServer]: ...
```

Harness 声明应区分：

```python
qwenpaw_skills_projection: bool
qwenpaw_mcp_projection: bool
provider_skills_discovery: bool
provider_mcp_discovery: bool
mcp_tool_allowlist: bool
```

前端只根据声明和统一 DTO 渲染，不按 Provider 名称决定布局。

## 7. UI/UX

第三方 Agent 页面显示能力摘要：

- `Skills · 继承 QwenPaw · 新会话生效`
- `MCP · 继承 QwenPaw · 3 个服务`
- `Codex 本地 MCP · 2 个 · 仅 Codex`
- `策略兼容性 · 工具白名单已支持 / 部分限制`

MCP 列表中每项必须显示：

- 来源：QwenPaw、Codex、Qoder 或未来 Provider。
- 范围：可共享或仅当前 Provider。
- 管理方式：可编辑或只读。
- 生效方式：运行时注入或 Provider 本地配置。

Skills 页面按管理权分组：

- `QwenPaw 管理`：可创建、编辑、启停、删除和导入，并在运行时投影到
  支持的第三方 Harness。
- `Provider 本地 Skills`：通过 Provider 稳定 API 发现，只读展示名称、
  描述、来源/scope、启用状态和“仅当前 Provider”。

Provider Skills 不自动导入、复制或投影给其他 Harness。QwenPaw 投影的
Skills 仍归属 `QwenPaw 管理`，不得在 Provider 只读分组重复展示。

Codex 使用 app-server `skills/list`。Qoder 使用 SDK 初始化结果
`get_server_info().skills`，并在 QwenPaw 启动的 Qoder 会话中加载
`user/project/local/plugin` Skills。Qoder SDK 模式固定禁用的 CLI bundled
Skills 不做配置文件猜测或绕过。

## 8. 跨平台与安全

- 所有路径使用 `pathlib.Path`，仅在 SDK/JSON 边界转成字符串。
- Windows 不依赖 symlink。
- stdio command 支持绝对路径和 PATH 命令。
- 子进程环境从最小增量构建，不修改系统或用户永久环境。
- 日志、异常、状态 API 对 env/header/token 做脱敏。
- Provider discovery 必须调用机器可读接口，不直接猜测用户配置文件。
- 能力 fingerprint 不包含明文秘密，只包含稳定的非秘密配置和密钥版本。

## 9. 验收标准

- 新建 Codex/Qoder Agent 后，默认获得当前频道启用的 QwenPaw Skills。
- QwenPaw MCP 能在 Codex/Qoder 会话中被列出和调用。
- QwenPaw MCP 不会写入 Provider 全局配置。
- 独立启动 Codex/Qoder 时看不到 QwenPaw 的运行时注入。
- QwenPaw 可以只读展示 Codex 可发现的本地 MCP，并明确“仅 Codex”。
- 不同 Harness 通过同一公共模型接入，不在 workspace/chat 入口硬编码。
- macOS、Linux 和 Windows 的路径与进程环境测试通过。
- 明文 MCP 密钥不出现在持久化文件、状态响应和测试日志中。

## 10. 实施顺序

1. 公共模型、Resolver 和 capability 声明。
2. Skills：Codex extra roots、Qoder Plugin。
3. MCP：Qoder SDK 投影、Codex app-server 配置投影。
4. Codex Provider MCP discovery。
5. 控制面来源/范围/兼容性展示。
6. 定向单测、前端测试和文件级 pre-commit。

详细进度见同目录 `IMPLEMENTATION_CHECKLIST.md`。
