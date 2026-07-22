# 集成测试

[English](README.md)

通过真实子进程对 QwenPaw FastAPI 应用做端到端的 HTTP 冒烟测试。每个测试
文件拥有自己的 QwenPaw app 子进程,绑定随机端口,工作目录隔离 —— 不需要
任何真实的 API key 或外部服务。

---

## 运行

```bash
# 全量(~3 分钟)
make test-integration
# 或直接:
pytest tests/integration/ --no-cov

# 按优先级(PR 必跑 / 每夜回归 / 全面契约)
pytest tests/integration/ -m p0 --no-cov   # ~2 分钟,PR 必跑冒烟
pytest tests/integration/ -m p1 --no-cov   # 每夜 / 合入回归
pytest tests/integration/ -m p2 --no-cov   # 异常路径与契约

# 单文件
pytest tests/integration/test_agents.py -v --no-cov

# 单用例
pytest tests/integration/test_agents.py::test_api_agents_list_create_get_delete -v --no-cov
```

测试串行执行(未在 `pytest-xdist` 下验证)。`--no-cov` 跳过父进程覆盖率;
子进程覆盖率见 [覆盖率](#覆盖率可选)。

---

## 优先级 marker

测试按 **用户视角的影响** 标记,而非技术复杂度。新增用例时先问自己:

> *"如果它挂了,用户还能正常发消息并收到回复吗?"*
> 能 → `p1` 或 `p2`;不能 → `p0`。

### `p0` — 命脉(PR 必跑冒烟)

挂了产品基本不可用,每个 PR 必须通过。覆盖:

- **消息收发主链路** — `/api/messages/send` 核心流程、默认 agent 路由
- **Agent / Chat / Skills 核心 CRUD** — 列表、增、查、删、启停、system
  prompt 文件
- **全局配置** — 通道、心跳、MCP CRUD、workspace 运行时配置
- **全局安全 Guard** — file guard、tool guard、skill scanner
- **Tools 启停** — 直接影响 agent 运行时能力
- **API version** — 基础健康检查

运行:`pytest -m p0`(约 22 个用例,~2 分钟)。

### `p1` — 降级但能用(每夜 / 合入回归)

挂了体验降级,但默认值能让用户继续使用。覆盖:

- **设置项与 scoped 覆盖** — 语言、音频模式、时区、转录服务,以及通道/
  心跳/Guard 的 agent-scoped 版本
- **Workspace 文件** — 工作/记忆目录文件 CRUD,zip 导入导出,scoped 一致性
- **ACP / LLM 路由** — 开发者向特性
- **Plan / Cron** — 辅助功能
- **统计接口** — token 用量、插件/备份列表、agent 统计、auth 状态
- **辅助 API** — 文件预览、agent 排序、批量操作

运行:`pytest -m p1`(约 53 个用例)。

### `p2` — 契约(全面覆盖)

边界行为,不影响主流程。覆盖:

- **校验拒绝** — `*_rejected` 系列(重名、非法 payload、非 zip 上传)
- **404 处理** — `*_returns_404`、`missing_*` 系列
- **批量部分成功** — 批量操作中部分成功的分支
- **隔离边界** — `*_isolated_*`、跨 agent 边界用例
- **HEAD 请求与契约** — `*_minimal_contract`、文件预览 HEAD
- **版本元数据** — 包版本、PEP 440 合规

运行:`pytest -m p2`(约 30 个用例)。

---

## 文件分布

| 文件 | 覆盖范围 |
|---|---|
| `test_agents.py` | Agent CRUD、排序、启停 |
| `test_chats_global.py` | 全局 `/api/chats`(CRUD、批量、隔离) |
| `test_chats_agent_scoped.py` | Agent-scoped chats |
| `test_workspace_files.py` | 工作/记忆目录文件、zip 导入导出 |
| `test_workspace_running_config.py` | 运行时配置(全局 + scoped) |
| `test_workspace_agent_settings.py` | Agent-scoped workspace 设置(语言、音频、prompt、转录、记忆) |
| `test_heartbeat.py` | 心跳配置(全局 + scoped) |
| `test_channels_config.py` | 通道配置 + 健康/重启 |
| `test_security_config.py` | File guard、tool guard、skill scanner |
| `test_agent_routing_config.py` | ACP、LLM 路由、白名单、时区 |
| `test_skills_global.py` | 全局 skills(CRUD、批量、校验) |
| `test_skills_agent_scoped.py` | Agent-scoped skills |
| `test_mcp.py` | MCP 客户端生命周期 |
| `test_messages_files.py` | 发送消息 + 文件预览 |
| `test_plan.py` | Plan 配置 |
| `test_cron.py` | Agent-scoped cron 任务 |
| `test_console.py` | Console 专属接口(chat stop、upload) |
| `test_console_metadata.py` | 插件/备份/token 用量/auth/agent 统计列表 |
| `test_settings_envs.py` | Settings + 持久化环境变量 |
| `test_tools.py` | Tools 启停与异步执行 |
| `test_app_startup.py` | App 就绪、console 入口/fallback |
| `test_version.py` | 包版本元数据(不拉 app 子进程) |

---

## `app_server` 工作原理

`tests/integration/conftest.py::app_server` 是 **module-scoped** fixture:
每个测试文件得到自己的 QwenPaw app 子进程(随机端口),同一文件内的所有
用例共享该子进程。跨文件隔离通过重新拉起子进程 + 全新 tmp 目录实现。

**用例必须在文件内使用唯一的资源 id**(例如
`agent_id = "integ_<scope>_01"`)以避免共享子进程内的命名冲突 —— 当前
约定已经这样做了。

Fixture 行为:

- 启动前清理 11 个敏感环境变量(`OPENAI_API_KEY`、`DASHSCOPE_API_KEY`、
  各 IM token 等)
- 强制 `QWENPAW_AUTH_ENABLED=false` 与 `NO_PROXY=*`
- 通过 `socket.bind(0)` 分配空闲端口
- 轮询 `/api/version` 最长 60 秒作为就绪信号
- 关停时使用 **SIGINT**(不是 SIGTERM),让 uvicorn 的 atexit 钩子能正常
  flush(子进程覆盖率数据依赖这一点;SIGTERM 经常会跳过)
- HTTP 超时 **15 秒**,吸收冷启动延迟(例如 ACP getter 首次访问需要 4-5
  秒)

---

## 覆盖率(可选)

默认 `pytest --cov` 只看到测试进程本身,对真实 app 几乎零覆盖。要采集
**app 子进程**的覆盖率:

```bash
QWENPAW_INTEGRATION_COVERAGE=1 pytest tests/integration/ --no-cov
```

执行流程:

1. 在 `.integration_coverage/` 写入 coverage rcfile,使用 **绝对路径**
   `source=…/src/qwenpaw`
2. 每个子进程通过 `COVERAGE_PROCESS_START` 与 `COVERAGE_FILE` 注入
3. 会话结束后合并并行数据文件,生成
   `htmlcov-integration/index.html`

> ⚠️ 此模式必须传 `--no-cov` —— 否则 `pytest-cov` 会因为父进程接近零
> 覆盖率而触发 `fail_under=30` 阈值,直接 fail 整轮。

此流程**未在 `pytest-xdist` 下验证**。

---

## 添加新用例

1. **按业务子域选文件**(参考 [文件分布](#文件分布))或新建
   `test_<subdomain>.py`。
2. **标记优先级** 用 `@pytest.mark.integration` + `p0` / `p1` / `p2`
   之一(参考 [优先级 marker](#优先级-marker))。
3. **使用唯一资源 id**(例如 `integ_<feature>_<seq>`)。
4. **文档化用例**,在函数顶部说明 purpose / flow / API endpoints。参考
   现有用例模板:

   ```python
   @pytest.mark.integration
   @pytest.mark.p1
   def test_my_feature_put_get_roundtrip(app_server) -> None:
       """Test purpose:
       - Verify ...

       Test flow:
       1. ...

       API endpoints:
       - PUT ...
       - GET ...
       """
   ```

5. **断言失败信息总是带 `app_server.logs_tail()`**,这样失败时能看到后端
   日志:

   ```python
   assert resp.status_code == 200, app_server.logs_tail()
   ```

---

## 已知约束

- **仅支持串行**:未在 `pytest-xdist` 下验证。
- **冷启动开销**:每个文件重新拉起 app 子进程(~4 秒 setup)。全量约 3
  分钟,P0 子集约 2 分钟。
- **不调真实 LLM**:消息测试走 `console` 通道,不触发模型 provider。
- **不打通真实通道 I/O**:只覆盖通道的配置层,IM webhook / long-poll
  路径不在范围内。
- **覆盖率模式仅单 worker**:`QWENPAW_INTEGRATION_COVERAGE=1` 不能与
  `pytest-xdist` 并用。
