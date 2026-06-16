# 审计日志完整性保护关键技术总结

本文只总结当前仓库已经落地的审计日志完整性保护机制，不展开未实现的 PRD 设想。

## 实现落点

- 边缘审计与完整性核心：`src/qwenpaw/security/audit_foundation.py`
- 高风险工具真实执行边界：`src/qwenpaw/agents/tool_guard_mixin.py`
- 控制台请求侧预判与拒绝投影：`src/qwenpaw/app/routers/console.py`
- 审批侧二次阻断：`src/qwenpaw/app/routers/approval.py`
- 云侧独立镜像与时间线：`deploy/api/store.py`
- 运营可视化边界：`deploy/web`

## 关键技术

### 1. 本地追加式账本与原子落盘

审计事件按单事件文件写入 `inbox_traces`，并通过 `_atomic_write()` 使用“临时文件 + 原子替换”落盘。这样既保留本地取证能力，也降低了半条记录落盘的风险。

### 2. 哈希链连续性保护

每条关键事件都带 `prior_hash` 和 `current_hash`，后一条记录引用前一条链头。删除、替换或重排链中事件会破坏连续性。对 `USER_CONFIRMATION`，当前实现还区分了业务摘要 `confirmation_digest` 和链式哈希 `current_hash`，避免把业务摘要误用为连续性锚点。

### 3. 检查点锚定

`audit_chain_checkpoint.json` 保存最近可信链头，包括 `run_id`、`current_hash`、`continuity_anchor` 和时间戳。它是链外锚点，用来发现“trace 还在但 checkpoint 丢失”这类尾部篡改或删除行为。当前 `lock_mode_required()` 就基于这一规则触发不可信状态。

### 4. 完整性失效后的 `UNTRUSTED` 锁定

检查点缺失或连续性异常不会只产生告警，而会写入 `AUDIT_INTEGRITY_LOCKDOWN` 事件并进入 `UNTRUSTED`。随后系统在三个边界拒绝高风险动作：控制台请求入口、审批放行入口和工具真实执行边界。重点是“真实执行边界必须拦住”。

### 5. 先固化证据，再释放高风险副作用

`write_confirmation_record()` 会先把 `USER_CONFIRMATION` 写入本地审计链并更新检查点，之后才允许高风险动作进入释放阶段。这样可以保证“确认”是链上的先决条件，而不是事后补记。

### 6. 基于运行时上下文的确认绑定

`capture_runtime_confirmation_context()` 会把用户、会话、渠道、代理、插件、工具和确认短语绑定进 `confirmation_digest`。因此记录不仅证明“有人确认过”，还能证明“确认的是哪条具体执行链”。

### 7. 拒绝事件凭证与链头绑定

被阻断的高风险请求会生成 `Security_Rejection_Nonce`，其绑定材料包含 `run_id`、`session_id`、`user_id`、`tool_name` 和 `current_hash`。这让拒绝凭证不是静态字符串，而是与当次 trace 和链头状态绑定的可校验标识。

### 8. 云侧独立镜像与恢复握手

`deploy/api/store.py` 独立实现 `canonical_json()`、`derive_shadow_hash()` 和 `derive_lockdown_shadow_hash()`，不直接信任边缘侧结论。锁定事件会形成本地哈希曲线、云侧影子曲线和 `fork_point`。恢复阶段必须走显式握手，由云侧返回 `shadow_hash`、`trust_state` 和 `recovery_required`，未恢复前不允许继续高风险执行。

### 9. `edge_timestamp_ns` 与外部可观测化

云侧强制要求 `edge_timestamp_ns`，并据此计算 `alert_latency_ms`，避免服务端伪造“看起来实时”的告警。关键拒绝和锁定事件会通过 SSE 投影到 Security Center，Web 端展示 Voucher、信任态、恢复进度、哈希分叉曲线和事件日志。

## 整体效果

当前实现已经形成一条完整保护链：关键事件先落边缘审计链，再由哈希链和检查点保障连续性；一旦发现异常，系统进入 `UNTRUSTED` 并在真实执行边界阻断高风险操作；随后再把关键事件投影到云侧和运营界面，形成独立可观测点。

## 本地开发：重置审计连续性状态

当 `inbox_traces/*.json` 与 `audit_chain_checkpoint.json` 不一致（例如只删了 checkpoint、或 trace 被手工改动）时，`lock_mode_required()` 会进入 `UNTRUSTED`，所有工具（含 `read_file`）在真实执行边界被阻断。

本地开发可运行 **`extension/reset-audit-state.ps1`**（Windows）或 **`extension/reset-audit-state.sh`**（Unix），在 **停止 QwenPaw 进程后** 清除：

- `<WORKING_DIR>/audit_chain_checkpoint.json`
- `<WORKING_DIR>/inbox_traces/*.json`

可选 `-IncludeSecurityCenter` 同时清空 Security Center 本地 store / data 目录。脚本**不会**改动 `workspaces/`、`config.json` 或 `integrity-protection/file-baseline/`。

WORKING_DIR 解析顺序：`QWENPAW_WORKING_DIR` / `COPAW_WORKING_DIR` → 存在则 `~/.copaw` → 否则 `~/.qwenpaw`。

## 结论

QwenPaw 当前实现中的审计日志完整性保护，本质上是“本地链式证据 + 检查点锚定 + `UNTRUSTED` 阻断 + 云侧独立镜像 + 运营外显”的组合。它已经具备发现篡改、阻断高风险继续执行，并把异常同步暴露给云侧和运营面的闭环能力。