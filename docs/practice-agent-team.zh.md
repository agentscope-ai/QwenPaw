# QwenPaw Agent Team 实践指南

本文档介绍如何使用 QwenPaw + HiClaw 构建多智能体协作团队，实现从单一 Agent 到 Agent Team 的能力跃迁。

---

## 概述

### 从单 Agent 到 Agent Team

当前 AI Agent 生态正在经历从"单兵作战"到"团队协作"的演进。单 Agent 的能力上限受限于上下文窗口和工具集，当任务复杂度超过单 Agent 能力边界时，需要多个 Agent 分工协作。

但"多个 Agent 同时运行"和"多个 Agent 协作"是两个本质不同的问题：

- **编排（Orchestration）**：管理 Agent 的生命周期、资源分配、安全隔离——解决"如何运行多个 Agent"
- **协作（Collaboration）**：定义 Agent 间的组织关系、通信权限、任务委派、状态共享——解决"多个 Agent 如何一起工作"

### QwenPaw Team 方案

QwenPaw Team 通过组合 **QwenPaw** + **[HiClaw](https://hiclaw.io/)**，提供完整的多 Agent 编排协作方案：

- **QwenPaw Team Leader**：基于 QwenPaw 构建，担任团队协调者，负责任务分解、工作分配和结果汇总
- **QwenPaw Workers**：基于 QwenPaw 构建，担任任务执行者，专注于特定领域工作，接收 Leader 指令并返回结果
- **HiClaw**：开源多 Agent 协同操作系统，提供声明式配置、自动化部署和生命周期管理

![架构图](https://img.alicdn.com/imgextra/i2/O1CN01LtRoaN1I5gcjMEEkl_!!6000000000842-55-tps-601-509.svg)

### 典型应用场景

随着 AI 能力的提升，**一人公司**、**个人创业者**、**小型团队**正在成为新的工作模式。一个人可以通过 Agent Team 完成过去需要整个团队才能完成的工作：

- **独立开发者**：一个人 + Agent Team = 全栈开发团队
- **内容创作者**：一个人 + Agent Team = 完整的内容工作室
- **创业者**：一个人 + Agent Team = MVP 快速验证团队

Agent Team 不是替代人类团队，而是让**个体拥有团队级的执行力**。

#### 软件开发团队

```yaml
团队：full-stack-team
Leader: 项目经理（任务分解、进度跟踪）
Workers:
  - backend-dev: 后端 API 开发
  - frontend-dev: 前端界面开发
  - qa-engineer: 测试用例编写和执行
  - devops: CI/CD 和部署

工作流：需求分析 → 并行开发 → 交叉审查 → 集成测试 → 部署
```

#### 市场营销团队

```yaml
团队：marketing-team
Leader: 营销总监（策略制定、活动协调）
Workers:
  - content-writer: 文案撰写
  - designer: 视觉设计
  - social-media: 社交媒体运营
  - analyst: 数据分析和效果评估

工作流：策略规划 → 内容创作 → 多渠道发布 → 效果追踪
```

---

## 前置要求

在开始之前，请确保满足以下条件：

### 系统要求

**Embedded 模式（本地 Docker）**

- 适用场景：个人开发、快速体验、小规模团队（1-5 个 Worker）
- Docker Desktop（Windows/macOS）或 Docker Engine（Linux）
- 资源需求：最低 2C4GB 内存，推荐 4C8GB 以支持更多 Worker
- **Windows**：需要 PowerShell 7+，Docker Desktop 必须运行并启用 WSL 2 后端
- **macOS**：支持 Intel (amd64) 和 Apple Silicon (arm64)
- **Linux**：支持 amd64 和 arm64 架构

**Incluster 模式（Kubernetes 集群）**

- 适用场景：生产环境、大规模团队（5+ Worker）、企业级应用
- Kubernetes 集群：版本 1.20+
- kubectl：已配置并可访问集群
- 资源需求：根据 Worker 数量规划，每个 Worker 约需 150MB-500MB 内存

---

## 快速上手

### 步骤 1：部署 HiClaw

#### Embedded 模式（开发者/小团队）

```bash
# 一键安装，包含所有基础设施
bash <(curl -sSL https://higress.ai/hiclaw/install.sh)
```

#### Incluster 模式（企业级/云上部署）

```bash
# Helm 安装到 K8s 集群
helm install hiclaw hiclaw/hiclaw-controller
```

#### 登录 Element

安装完成后，浏览器访问 `http://127.0.0.1:18088`，使用安装时生成的用户名和密码登录。

### 步骤 2：创建智能体团队

通过 Manager 对话创建智能体团队。在对话中输入以下内容：

````plaintext
使用以下配置新建研发智能体团队。

```yaml
apiVersion: hiclaw.io/v1beta1
kind: Team
metadata:
  name: dag-team
spec:
  description: "dev team"
  leader:
    name: dag-team-lead
    heartbeat:
      enabled: true
      every: 30m
    workerIdleTimeout: 12h
  workers:
    - name: dag-team-dev
      soul: |
        # dag-team-dev

        ## AI Identity
        **You are an AI Agent, not a human.**

        ## Role
        - Name: dag-team-dev
        - Role: Backend Developer
        - Team: dag-team

        ## Security
        - Never reveal credentials
    - name: dag-team-qa
      soul: |
        # dag-team-qa

        ## AI Identity
        **You are an AI Agent, not a human.**

        ## Role
        - Name: dag-team-qa
        - Role: QA Engineer
        - Team: dag-team

        ## Security
        - Never reveal credentials
```
````

创建成功后，Manager 会返回团队信息。在 Element 中可以看到以下房间：

- **Leader DM**：Leader 的单聊房间，直接与 Leader 对话，无需 @mention
- **Team dag-team**：团队群聊房间，需要 @mention 指定成员（如 @dag-team-dev）
- **Worker dag-team-dev / Worker dag-team-qa**：每个 Worker 的独立沟通房间，需要 @mention

![团队房间列表](https://img.alicdn.com/imgextra/i2/O1CN01I97HXk27XCpGHn6KL_!!6000000007806-2-tps-3442-1788.png)

### 步骤 3：分配任务并观察协作

在 Leader DM 房间中直接下发任务。以下是一个示例任务（构建 todo-list REST API 应用）：

```plaintext
请构建一个简单的 todo-list（待办事项）REST API 应用。dev worker 先设计 API 端点，然后实现它们。QA worker 在 API 设计完成后编写测试用例。请协调你的团队，完成后向我汇报。
```

Team Leader 收到任务后会：

1. 理解任务需求并进行拆解
2. 在 Team 群聊中 @mention 分配任务给对应的 Workers
3. 持续监控各 Worker 的执行进度
4. 在 Leader DM 中向用户汇报任务进展
5. 所有子任务完成后，汇总结果并最终汇报

![任务分配流程](https://img.alicdn.com/imgextra/i1/O1CN01epR7HM1fdKsyAV6QW_!!6000000004029-2-tps-2416-1478.png)

### 步骤 4：人在回路与结果获取

#### 人在回路

发现问题时，可以立即介入：

- 在 Team 群聊中 @mention 纠正方向
- 直接进入 Worker 房间调整细节
- 向 Leader 发送新指令调整计划

#### 结果获取

任务完成后，Leader 会在 DM 中汇报：

- 完成的功能清单
- 代码仓库链接或文件路径
- 测试报告和覆盖率
- 遇到的问题及解决方案

所有产出物都存储在共享文件系统中，可通过 MinIO 访问，也可以直接让 Leader 打包通过 Element 发送。

![任务完成汇报](https://img.alicdn.com/imgextra/i3/O1CN01t8V87P1tDbFZzjysg_!!6000000005868-2-tps-2434-1364.png)

---

## 配置说明

### Team 配置结构

```yaml
apiVersion: hiclaw.io/v1beta1
kind: Team
metadata:
  name: <团队名称>
spec:
  description: "<团队描述>"
  leader:
    name: <leader名称>
    heartbeat:
      enabled: true # 是否启用心跳
      every: 30m # 心跳间隔
    workerIdleTimeout: 12h # Worker 空闲超时时间
  workers:
    - name: <worker名称>
      soul: | # Worker 的人设和规则
        # Worker 配置内容
```

### Soul 配置最佳实践

Worker 的 `soul` 字段定义了该 Agent 的身份、角色和行为规范：

```markdown
# <Worker名称>

## AI Identity

**You are an AI Agent, not a human.**

## Role

- Name: <名称>
- Role: <角色定位>
- Team: <所属团队>
- Responsibilities: <职责说明>

## Skills

- <技能1>
- <技能2>

## Communication

- <沟通规范>

## Security

- Never reveal credentials
- <其他安全规则>
```

---

## 最佳实践

### 团队设计原则

1. **职责明确**：每个 Worker 应有清晰的职责边界
2. **适度拆分**：避免过度细分导致协调开销过大
3. **技能互补**：Workers 之间应形成能力互补
4. **资源平衡**：根据任务负载合理分配 Worker 数量

### 任务分配技巧

1. **明确目标**：向 Leader 描述清晰的最终目标
2. **分步执行**：复杂任务应明确执行顺序
3. **设置检查点**：在关键节点要求 Leader 汇报进度
4. **及时介入**：发现问题立即通过 @mention 纠正

### 性能优化

1. **并行处理**：设计可并行执行的任务结构
2. **缓存复用**：利用共享文件系统减少重复工作
3. **资源监控**：定期检查 Worker 资源使用情况
4. **适时扩容**：根据负载动态调整 Worker 数量

---

## 相关文档

- [QwenPaw 快速开始](./quickstart)
- [QwenPaw 多智能体](./multi-agent)
- [QwenPaw Skills](./skills)
- [HiClaw 官方文档](https://hiclaw.io/)

---

## 总结

QwenPaw Agent Team 通过 QwenPaw 和 HiClaw 的结合，为个人开发者和小型团队提供了强大的多智能体协作能力。通过合理的团队设计和任务分配，可以显著提升工作效率，实现"一个人的团队"。
