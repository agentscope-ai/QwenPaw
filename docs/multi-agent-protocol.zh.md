# 多智能体通信协议（Multi-Agent Communication Protocol）

## 概述

本协议定义了 CoPaw 框架中多个智能体之间的通信机制，支持真正并行执行和任务协调。

## 架构设计

### 核心组件

```
┌─────────────────┐
│   Coordinator   │ ← 协调器（汤圆）
│   (主进程)      │
└────────┬────────┘
         │
         ├─ 启动进程 1 ──→ ┌──────────────┐
         │                 │ Agent A      │
         │                 │ (独立进程)   │
         │                 └──────────────┘
         │
         └─ 启动进程 2 ──→ ┌──────────────┐
                           │ Agent B      │
                           │ (独立进程)   │
                           └──────────────┘
```

### 进程模型

- **协调器**: 主进程，负责任务拆解、调度、汇总
- **智能体**: 独立 Python 进程，执行具体任务
- **通信**: 通过文件系统进行进程间通信（IPC）

## 通信协议

### 任务文件（task_<agent>.json）

```json
{
  "id": "TASK-20260311-001",
  "agent": "linglong",
  "type": "content_creation",
  "created_at": "2026-03-11T21:00:00",
  "status": "PENDING",
  "platforms": ["wechat", "xiaohongshu"],
  "topic": "AI 军团协作"
}
```

### 结果文件（result_<agent>.json）

```json
{
  "agent": "linglong",
  "task_type": "content_creation",
  "status": "DONE",
  "started_at": "2026-03-11T21:00:01",
  "completed_at": "2026-03-11T21:00:10",
  "results": [...],
  "summary": "完成 2 个平台的内容创作"
}
```

## 执行流程

### 1. 任务创建

```python
coordinator.create_task(
    agent_name='linglong',
    task_type='content_creation',
    platforms=['wechat', 'xiaohongshu']
)
```

### 2. 并行启动

```python
from concurrent.futures import ThreadPoolExecutor
import subprocess

def execute_parallel(tasks):
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        futures = [
            executor.submit(
                lambda a, t: subprocess.Popen(
                    [sys.executable, f'agent_{a}.py', t],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                ),
                agent, task
            )
            for agent, task in tasks
        ]
        results = [f.result() for f in as_completed(futures)]
    return results
```

### 3. 状态监控

协调器定期检查任务文件状态：
- `PENDING` - 等待执行
- `RUNNING` - 执行中
- `DONE` - 完成
- `FAILED` - 失败

## 性能数据

| 指标 | 数值 |
|------|------|
| 进程启动时间 | <0.1 秒/进程 |
| 通信开销 | ~0.01 秒/文件 IO |
| 并行效率 | 45-90%（取决于任务类型） |
| 内存占用 | ~50MB/进程 |

## 最佳实践

### 1. 任务粒度

- ✅ 适合：独立任务、IO 密集、CPU 密集
- ❌ 不适合：频繁通信、微秒级延迟要求

### 2. 错误处理

```python
try:
    result = subprocess.run(cmd, timeout=300)
    if result.returncode != 0:
        # 重试机制
        retry()
except subprocess.TimeoutExpired:
    # 超时处理
    handle_timeout()
```

### 3. 资源管理

- 限制最大进程数（建议 <10）
- 设置超时时间（避免无限等待）
- 清理临时文件（task_*, result_*）

## 扩展方向

### 短期（1-2 周）

- [ ] 共享内存（multiprocessing.Manager）
- [ ] 日志集中
- [ ] 重试机制

### 中期（1-2 月）

- [ ] 消息队列（Redis/RabbitMQ）
- [ ] 任务优先级
- [ ] 智能体池

### 长期（3-6 月）

- [ ] 微服务化
- [ ] 分布式追踪
- [ ] 自动扩缩容

## 示例代码

完整实现参考：
- `coordinator.py` - 协调器
- `agent_executor.py` - 执行器
- `agent_linglong.py` - CMO 智能体
- `agent_luban.py` - CTO 智能体

## 相关资源

- [Python multiprocessing](https://docs.python.org/3/library/multiprocessing.html)
- [CoPaw 路线图](https://github.com/agentscope-ai/CoPaw/blob/main/website/public/docs/roadmap.zh.md)
- [多智能体系统论文](https://arxiv.org/abs/2308.11339)

---

*本文档基于 CoPaw 框架的多智能体协作实践编写。*
