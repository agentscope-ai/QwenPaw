# Service Class None Start Method Fix

## 用户反馈

```
When service_class is None, _start_service() only runs post_init and
ignores start_method. Descriptors like channel_manager,
agent_config_watcher, and mcp_config_watcher specify a start_method,
so they will never be started with the current logic. A concrete fix is
to capture the object returned/registered by post_init (or read it from
self.services[name]) and then invoke start_method on it when present.
```

### 关键问题

**这和之前的 post_init reuse 问题不是同一回事！**

- **之前的问题**（已修复）：Reused 服务的 `post_init` 被完全跳过 → 导致无法连接到新 runner
- **这次的问题**（新发现）：`service_class=None` 的服务的 `start_method` 永远不会被调用 → 导致服务未启动

## 问题描述

### 受影响的服务

以下服务使用 `service_class=None` + `post_init` + `start_method` 模式：

```python
# 1. channel_manager
ServiceDescriptor(
    name="channel_manager",
    service_class=None,  # ← No auto-instantiation
    post_init=create_channel_service,  # Creates and returns ChannelManager
    start_method="start_all",  # ← NEVER CALLED!
    stop_method="stop_all",
)

# 2. agent_config_watcher
ServiceDescriptor(
    name="agent_config_watcher",
    service_class=None,
    post_init=create_agent_config_watcher,  # Creates and returns watcher
    start_method="start",  # ← NEVER CALLED!
    stop_method="stop",
)

# 3. mcp_config_watcher
ServiceDescriptor(
    name="mcp_config_watcher",
    service_class=None,
    post_init=create_mcp_config_watcher,
    start_method="start",  # ← NEVER CALLED!
    stop_method="stop",
)
```

### 根本原因

旧的 `_start_service()` 逻辑：

```python
if descriptor.service_class:
    service = descriptor.service_class(**init_kwargs)
    self.services[name] = service
else:
    service = None  # ← Bug!

# Always call post_init
if descriptor.post_init:
    result = descriptor.post_init(self.workspace, service)
    await result  # ← result (服务对象) 被丢弃！

# Call start method only for new services
if not is_reused and descriptor.start_method and service:  # ← service 是 None!
    start_fn = getattr(service, descriptor.start_method)
    ...
```

**问题流程**：
1. `service_class=None` → `service = None`
2. `post_init()` 创建并返回服务对象 → **返回值被丢弃**
3. `start_method` 检查 `and service` → **永远 False**
4. **服务从未启动！**

### 验证问题

```python
# 测试 AgentConfigWatcher 是否启动
watcher = ws._service_manager.services.get('agent_config_watcher')
print(f'_task: {watcher._task}')  # ← None (未启动)
```

**结果**：
```
AgentConfigWatcher found
  _task: None  ← Bug! start() 从未被调用
```

如果 `start()` 被调用，`_task` 应该是一个 `asyncio.Task` 对象。

## 解决方案

### 核心修复

修改 `_start_service()` 来**捕获 post_init 返回值**：

```python
# Always call post_init (for wiring to new runner)
if descriptor.post_init:
    result = descriptor.post_init(self.workspace, service)
    if asyncio.iscoroutine(result):
        result = await result

    # ✅ 捕获服务对象从 post_init 返回值或 self.services
    if result is not None:
        service = result
        # Ensure it's registered in services dict
        if name not in self.services:
            self.services[name] = service
    elif service is None:
        # post_init might have registered service in self.services
        service = self.services.get(name)

# Call start method only for new services
if not is_reused and descriptor.start_method and service:  # ← 现在 service 不是 None!
    start_fn = getattr(service, descriptor.start_method)
    ...
```

### 代码重构

为了通过 pylint "too-many-branches" 检查，将 `_start_service()` 拆分为三个辅助方法：

```python
async def _start_service(self, descriptor: ServiceDescriptor) -> None:
    """Start a single service."""
    service = await self._get_or_create_service(descriptor, is_reused)
    service = await self._run_post_init(descriptor, service, name)
    await self._run_start_method(descriptor, service, is_reused)

async def _get_or_create_service(
    self,
    descriptor: ServiceDescriptor,
    is_reused: bool,
) -> Any:
    """Get existing or create new service instance."""
    if is_reused:
        return self.services.get(descriptor.name)

    if not descriptor.service_class:
        return None

    # Instantiate service...
    return service

async def _run_post_init(
    self,
    descriptor: ServiceDescriptor,
    service: Any,
    name: str,
) -> Any:
    """Run post_init hook and capture returned service."""
    if not descriptor.post_init:
        return service

    result = descriptor.post_init(self.workspace, service)
    if asyncio.iscoroutine(result):
        result = await result

    # Capture service from return value or self.services
    if result is not None:
        service = result
        if name not in self.services:
            self.services[name] = service
    elif service is None:
        service = self.services.get(name)

    return service

async def _run_start_method(
    self,
    descriptor: ServiceDescriptor,
    service: Any,
    is_reused: bool,
) -> None:
    """Run start method on service if applicable."""
    if is_reused or not descriptor.start_method or not service:
        return

    start_fn = getattr(service, descriptor.start_method)
    if asyncio.iscoroutinefunction(start_fn):
        await start_fn()
    else:
        start_fn()
```

## 验证结果

### 1. AgentConfigWatcher 启动成功

```
AgentConfigWatcher:
  ✓ Created: AgentConfigWatcher
  ✓ _task: <Task pending name='agent_config_watcher_default'...>
  ✓ Started: True  ← 修复成功！
```

日志确认：
```
INFO src/copaw/app/agent_config_watcher.py:81 | AgentConfigWatcher
started for agent default (poll=2.0s, path=.../agent.json)
```

### 2. MCPConfigWatcher 启动成功

```
MCPConfigWatcher:
  ✓ Created: MCPConfigWatcher
  ✓ _task: <Task pending name='mcp_config_watcher'...>
  ✓ Started: True  ← 修复成功！
```

### 3. Reload 后正确重启

```
Before reload:
  AgentConfigWatcher task: <Task pending...>

After reload:
  AgentConfigWatcher task: <Task pending...>  ← 新的 task
  New instance: True  ← 新创建的实例，正确启动
```

### 4. 所有测试通过

```
✓ test_component_reuse.py: 5/5 tests passed
✓ test_all_reload_mechanisms.py: 4/4 tests passed
✓ pre-commit: All checks passed
```

## 技术要点

### 两种 Post-Init 模式

#### 模式 1: 标准服务（返回 None）
```python
# memory_manager
post_init=lambda ws, mm: setattr(
    ws._service_manager.services["runner"],
    "memory_manager",
    mm,  # 已有 mm 参数，不需要返回
)
```
- `service_class` 存在 → ServiceManager 自动创建
- `post_init` 接收服务实例，执行 wiring，**不返回值**

#### 模式 2: 工厂创建（返回服务对象）
```python
# agent_config_watcher
async def create_agent_config_watcher(ws, _):
    watcher = AgentConfigWatcher(...)
    ws._service_manager.services["agent_config_watcher"] = watcher
    return watcher  # ← 返回服务对象！
```
- `service_class=None` → ServiceManager 不创建
- `post_init` 负责创建**和** wiring，**返回服务对象**

### Start Method 调用时机

```
┌─────────────────────────────────────────┐
│ _start_service()                        │
└──────────┬──────────────────────────────┘
           │
           ▼
    ┌──────────────────┐
    │ Get/Create       │
    │ service_class?   │
    │   Yes → create   │
    │   No  → None     │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │ post_init()      │
    │ - Wire to runner │
    │ - Return service │  ← 关键修复：捕获返回值
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │ Capture service  │
    │ from return or   │
    │ self.services    │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │ start_method()   │  ← 现在可以正确调用
    │ if not reused    │
    └──────────────────┘
```

## 影响范围

### 修改的文件

1. **`src/copaw/app/workspace/service_manager.py`**
   - 修改 `_start_service()` 捕获 post_init 返回值
   - 重构为三个辅助方法减少复杂度

### 向后兼容性

✅ **完全向后兼容**
- 模式 1（标准服务）：post_init 不返回值 → 使用原有 service 参数 ✅
- 模式 2（工厂创建）：post_init 返回服务对象 → 被捕获并用于 start_method ✅

## 两次修复的对比

| 维度 | Post-Init Reuse Fix | Service Class None Fix |
|------|---------------------|------------------------|
| **问题** | Reused 服务 post_init 被跳过 | service_class=None 服务 start_method 被跳过 |
| **受影响服务** | memory_manager, chat_manager | channel_manager, watchers |
| **症状** | runner.memory_manager = None | watcher._task = None |
| **根因** | `if reused: return` 太早 | `service = None` + 返回值被丢弃 |
| **修复** | 始终执行 post_init | 捕获 post_init 返回值 |

## 总结

用户的观察**完全正确**，这是一个独立于之前 reuse 问题的新 bug：

1. **问题**：`service_class=None` 的服务 `start_method` 从未被调用
2. **根因**：post_init 返回的服务对象被丢弃，导致 `service` 变量仍然是 `None`
3. **修复**：捕获 post_init 返回值或从 `self.services` 读取
4. **重构**：拆分为三个辅助方法提高可读性
5. **验证**：所有 watchers 正确启动，所有测试通过

这次修复确保了所有服务（无论 service_class 是否为 None）都能正确启动。
