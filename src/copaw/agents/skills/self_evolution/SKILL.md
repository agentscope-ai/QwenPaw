---
name: self_evolution
description: "自我进化引擎 - 自动错误捕获、模式检测、AI归因分析、进化仪表盘。支持周期性审视、经验学习、任务固化、闭环进化。"
metadata:
  {
    "builtin_skill_version": "1.0",
    "copaw":
      {
        "emoji": "🧬",
        "requires": {}
      }
  }
---

# Self-Evolution 自我进化引擎

让 AI Agent 具有自我进化能力，自动从错误中学习，持续改进。

## 核心功能

### 1. 自动错误捕获 (Auto Error Catcher)

自动捕获执行过程中的错误，并进行分类：

| 错误类型 | 说明 |
|----------|------|
| file_error | 文件相关错误 |
| permission_error | 权限错误 |
| import_error | 导入错误 |
| database_error | 数据库错误 |
| key_error | 字典键错误 |
| type_error | 类型错误 |
| value_error | 值错误 |
| timeout_error | 超时错误 |
| network_error | 网络错误 |
| parse_error | 解析错误 |
| encoding_error | 编码错误 |

### 2. 模式检测 (Pattern Detector)

自动分析 recurring（重复出现）的错误模式，找出根本原因。

### 3. AI 归因分析 (AI Attributor)

使用 5-Why 分析法，AI 自动归因错误的根本原因。

### 4. 进化仪表盘 (Evolution Dashboard)

可视化展示进化数据，包括：
- 错误趋势
- 模式分析
- 优化建议
- 进度追踪

### 5. 会话启动检查 (Session Startup Check)

每次会话启动时自动检查：
- AGENTS.md/MEMORY.md 大小是否超限
- 是否有待处理的进化项
- 记忆数据库健康状态
- 临时文件清理

## 使用场景

- 用户要求"分析错误"、"找出问题原因"
- 用户要求"自动优化"、"自我改进"
- 用户要求"查看进化状态"、"生成报告"
- 错误重复出现，需要找出模式

## 硬规则

### 必须记录错误上下文

捕获错误时，必须记录：
- 错误类型
- 错误消息
- 发生位置
- 调用栈
- 会话 ID

### 禁止跳过归因

每次错误后必须尝试归因，不能忽略。

### 输出格式

生成报告时使用 Markdown 格式，便于阅读和分享。

---

## 命令行使用

```bash
# 运行会话启动检查
python -m copaw.agents.skills.self_evolution session_startup

# 运行模式检测
python -m copaw.agents.skills.self_evolution detect_patterns

# 生成仪表盘报告
python -m copaw.agents.skills.self_evolution dashboard
```