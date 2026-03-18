# Service Reuse Post-Init Fix

## 问题描述

### 用户反馈
```
Service reuse currently skips the entire descriptor startup path.
For reused services like memory_manager / chat_manager, this means
post_init never runs (so the new runner won't be wired with the
reused instances), and start_method is never invoked/checked.
Consider still running post_init (and any required wiring) when a
service is marked reused, even if you skip construction and/or start_method.
```

### 核心问题

之前的 Service Manager 实现在处理 reused services 时，会**完全跳过**整个启动流程：

```python
async def _start_service(self, descriptor: ServiceDescriptor) -> None:
    if name in self.reused_services:
        return  # ← 完全跳过！包括 post_init

    # 创建服务...
    # 调用 post_init（连接到 runner）
    # 调用 start_method
```

这导致两个严重问题：

#### 1. 新 Runner 无法访问 Reused 组件

对于 `memory_manager`：
```python
# memory_manager 的 post_init
post_init=lambda ws, mm: setattr(
    ws._service_manager.services["runner"],
    "memory_manager",
    mm,  # ← 这个 setattr 被跳过！
)
```

**验证结果**：
```
第一次加载:
  Runner.memory_manager: <MemoryManager object> ✅

Reload 后:
  Runner: <新的 AgentRunner>
  Runner.memory_manager: None  ← ❌ Bug！
  Memory Manager: <旧的 MemoryManager>（复用了）
```

#### 2. ChatManager 每次都被重新创建

`create_chat_service` 是一个自定义的 post_init 钩子：
```python
async def create_chat_service(ws: "Workspace", _):
    cm = ChatManager(repo=chat_repo)  # ← 总是创建新的！
    ws._service_manager.services["chat_manager"] = cm
```

即使 `chat_manager` 被标记为 reusable，由于整个 post_init 被跳过，这个钩子也不会执行，导致 ChatManager 没有被正确处理。

## 解决方案

### 1. Service Manager 修改

修改 `_start_service()` 逻辑，**始终执行 post_init**：

```python
async def _start_service(self, descriptor: ServiceDescriptor) -> None:
    name = descriptor.name
    is_reused = name in self.reused_services

    if is_reused:
        # 获取已存在的服务实例
        service = self.services.get(name)
    else:
        # 创建新服务实例
        if descriptor.service_class:
            service = descriptor.service_class(**init_kwargs)
            self.services[name] = service
        else:
            service = None

    # ✅ 始终执行 post_init（用于连接到新 runner）
    if descriptor.post_init:
        result = descriptor.post_init(self.workspace, service)
        if asyncio.iscoroutine(result):
            await result

    # ✅ 只对新服务调用 start_method
    if not is_reused and descriptor.start_method and service:
        start_fn = getattr(service, descriptor.start_method)
        # ...
```

**关键设计**：
- ✅ Reused 服务：跳过创建、跳过 start_method、**执行 post_init**
- ✅ 新服务：创建、执行 post_init、调用 start_method

### 2. ChatManager Factory 修改

修改 `create_chat_service` 来处理 reuse 场景：

```python
async def create_chat_service(ws: "Workspace", service):
    if service is not None:
        # Reused ChatManager - 直接使用
        cm = service
        logger.info(f"Reusing ChatManager for {ws.agent_id}")
    else:
        # 创建新 ChatManager
        chats_path = str(ws.workspace_dir / "chats.json")
        chat_repo = JsonChatRepository(chats_path)
        cm = ChatManager(repo=chat_repo)
        ws._service_manager.services["chat_manager"] = cm
        logger.info(f"ChatManager created: {chats_path}")

    # 始终连接到新 runner
    ws._service_manager.services["runner"].set_chat_manager(cm)
```

**关键逻辑**：
- 检查 `service` 参数是否为 None
- 如果不是 None → reused，直接使用
- 如果是 None → 创建新的
- **始终**连接到新 runner

## 验证结果

### MemoryManager 连接修复

```
Reload 后:
  Runner.memory_manager: <MemoryManager object> ✅
  Memory Manager id: 5280397840 (相同)
  内存地址相同: True
  Runner 连接正确: True ✅
```

### ChatManager 复用修复

```
[Test 2] ChatManager Reuse
  Original ChatManager id: 13434746016
  After reload ChatManager id: 13434746016
  ChatManager reused: True ✅
```

### 完整测试结果

```
✓ ALL TESTS PASSED! (5/5)

- Test 1: MemoryManager Reuse
- Test 2: ChatManager Reuse
- Test 3: Runner is New Instance
- Test 4: Reused Components Tracking
- Test 5: Multiple Reloads Preserve Component Reuse
```

## 技术要点

### Reusable Service 的生命周期

```
┌─────────────────────────────────────────────────────────┐
│ Reload 触发                                              │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │ 提取 Reusable Services      │
    │ (memory_manager, chat_mgr)  │
    └──────────┬──────────────────┘
               │
               ▼
    ┌─────────────────────────────┐
    │ 创建新 Workspace            │
    │ - 新 Runner                 │
    │ - 新 Config                 │
    └──────────┬──────────────────┘
               │
               ▼
    ┌─────────────────────────────┐
    │ set_reusable_services()     │
    │ - 放入 services dict        │
    │ - 标记为 reused             │
    └──────────┬──────────────────┘
               │
               ▼
    ┌─────────────────────────────┐
    │ start_all()                 │
    └──────────┬──────────────────┘
               │
               ▼
    ┌─────────────────────────────┐
    │ _start_service()            │
    │ for memory_manager:         │
    │   ✓ 跳过创建（已存在）     │
    │   ✓ 执行 post_init          │ ← 关键修复！
    │     - 连接到新 runner       │
    │   ✓ 跳过 start_method       │
    └─────────────────────────────┘
```

### Post-Init 的两种模式

#### 模式 1: 标准服务（MemoryManager）
```python
ServiceDescriptor(
    name="memory_manager",
    service_class=MemoryManager,
    post_init=lambda ws, mm: setattr(
        ws._service_manager.services["runner"],
        "memory_manager",
        mm,
    ),
)
```
- `service_class` 存在 → ServiceManager 自动创建
- `post_init` 接收创建好的实例，执行 wiring

#### 模式 2: 自定义工厂（ChatManager）
```python
ServiceDescriptor(
    name="chat_manager",
    service_class=None,  # ← 无自动创建
    post_init=create_chat_service,  # ← 工厂负责创建
)
```
- `service_class=None` → ServiceManager 传递 `None` 或 reused instance
- `post_init` 负责创建**和** wiring

**关键**：模式 2 的 post_init **必须**检查 `service` 参数来判断是否 reused！

## 影响范围

### 修改的文件

1. **`src/copaw/app/workspace/service_manager.py`**
   - 修改 `_start_service()` 逻辑
   - 始终执行 post_init for reused services

2. **`src/copaw/app/workspace/service_factories.py`**
   - 修改 `create_chat_service()` 处理 reuse

### 向后兼容性

✅ **完全向后兼容**
- 标准服务（模式 1）：无需修改
- 自定义工厂（模式 2）：只需修改 post_init 检查 `service` 参数

## 总结

用户的观察**完全正确**，这是一个严重的架构缺陷：

1. **问题**：Reused services 完全跳过 post_init，导致无法连接到新 runner
2. **根因**：过度简化了 reuse 逻辑，假设"复用=什么都不做"
3. **修复**：区分"构造"和"连接"两个阶段
   - Reused: 跳过构造 + 跳过 start + **执行连接**
   - New: 执行构造 + **执行连接** + 执行 start
4. **验证**：所有测试通过，组件正确复用且正确连接

这次修复确保了 zero-downtime reload 机制的正确性和完整性。
