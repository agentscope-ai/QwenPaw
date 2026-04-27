# QwenPaw Agent Team Practice Guide

This guide introduces how to build multi-agent collaborative teams using QwenPaw + HiClaw, achieving the capability leap from single Agent to Agent Team.

---

## Overview

### From Single Agent to Agent Team

The AI Agent ecosystem is evolving from "solo operation" to "team collaboration." A single Agent's capability is limited by context window and toolset. When task complexity exceeds a single Agent's boundary, multiple Agents need to collaborate through division of labor.

However, "running multiple Agents simultaneously" and "multiple Agents collaborating" are two fundamentally different problems:

- **Orchestration**: Managing Agent lifecycle, resource allocation, and security isolation—solving "how to run multiple Agents"
- **Collaboration**: Defining organizational relationships, communication permissions, task delegation, and state sharing among Agents—solving "how multiple Agents work together"

### QwenPaw Team Solution

QwenPaw Team provides a complete multi-Agent orchestration and collaboration solution by combining **QwenPaw** + **[HiClaw](https://hiclaw.io/)**:

- **QwenPaw Team Leader**: Built on QwenPaw, serves as team coordinator, responsible for task decomposition, work allocation, and result aggregation
- **QwenPaw Workers**: Built on QwenPaw, serve as task executors, focusing on domain-specific work, receiving Leader instructions and returning results
- **HiClaw**: Open-source multi-Agent collaborative operating system, providing declarative configuration, automated deployment, and lifecycle management

![Architecture Diagram](https://img.alicdn.com/imgextra/i2/O1CN01LtRoaN1I5gcjMEEkl_!!6000000000842-55-tps-601-509.svg)

### Typical Use Cases

With the advancement of AI capabilities, **one-person companies**, **solo entrepreneurs**, and **small teams** are becoming new work models. One person can accomplish through Agent Team what previously required an entire team:

- **Independent Developers**: One person + Agent Team = Full-stack development team
- **Content Creators**: One person + Agent Team = Complete content studio
- **Entrepreneurs**: One person + Agent Team = MVP rapid validation team

Agent Team doesn't replace human teams but empowers **individuals with team-level execution capability**.

#### Software Development Team

```yaml
Team: full-stack-team
Leader: Project Manager (task decomposition, progress tracking)
Workers:
  - backend-dev: Backend API development
  - frontend-dev: Frontend UI development
  - qa-engineer: Test case writing and execution
  - devops: CI/CD and deployment

Workflow: Requirements analysis → Parallel development → Cross review → Integration testing → Deployment
```

#### Marketing Team

```yaml
Team: marketing-team
Leader: Marketing Director (strategy formulation, campaign coordination)
Workers:
  - content-writer: Copywriting
  - designer: Visual design
  - social-media: Social media operations
  - analyst: Data analysis and effectiveness evaluation

Workflow: Strategy planning → Content creation → Multi-channel distribution → Performance tracking
```

---

## Prerequisites

Before getting started, ensure the following conditions are met:

### System Requirements

**Embedded Mode (Local Docker)**

- Use Cases: Personal development, quick experience, small-scale teams (1-5 Workers)
- Docker Desktop (Windows/macOS) or Docker Engine (Linux)
- Resource Requirements: Minimum 2C4GB memory, recommended 4C8GB to support more Workers
- **Windows**: Requires PowerShell 7+, Docker Desktop must be running with WSL 2 backend enabled
- **macOS**: Supports Intel (amd64) and Apple Silicon (arm64)
- **Linux**: Supports amd64 and arm64 architectures

**Incluster Mode (Kubernetes Cluster)**

- Use Cases: Production environment, large-scale teams (5+ Workers), enterprise applications
- Kubernetes Cluster: Version 1.20+
- kubectl: Configured and accessible to cluster
- Resource Requirements: Plan according to Worker count, each Worker requires approximately 150MB-500MB memory

---

## Quick Start

### Step 1: Deploy HiClaw

#### Embedded Mode (Developers/Small Teams)

```bash
# One-click installation, includes all infrastructure
bash <(curl -sSL https://higress.ai/hiclaw/install.sh)
```

#### Incluster Mode (Enterprise/Cloud Deployment)

```bash
# Helm install to K8s cluster
helm install hiclaw hiclaw/hiclaw-controller
```

#### Login to Element

After installation, access `http://127.0.0.1:18088` in your browser and log in with the username and password generated during installation.

### Step 2: Create Agent Team

Create the agent team through Manager conversation. Enter the following in the conversation:

````plaintext
Create a development agent team using the following configuration.

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

After successful creation, Manager will return team information. In Element, you can see the following rooms:

- **Leader DM**: Leader's direct message room, communicate directly with Leader without @mention
- **Team dag-team**: Team group chat room, requires @mention to specify members (e.g., @dag-team-dev)
- **Worker dag-team-dev / Worker dag-team-qa**: Independent communication room for each Worker, requires @mention

![Creation Success Screenshot](https://img.alicdn.com/imgextra/i4/O1CN01gJ8rQW1xqlaELzi7h_!!6000000006495-2-tps-3452-1898.png)

### Step 3: Assign Tasks and Observe Collaboration

Assign tasks directly in the Leader DM room. Here's an example task (building a todo-list REST API application):

```plaintext
Please build a simple todo-list REST API application. The dev worker should first design the API endpoints, then implement them. The QA worker should write test cases after the API design is complete. Please coordinate your team and report to me when finished.
```

Upon receiving the task, Team Leader will:

1. Understand task requirements and decompose them
2. @mention and assign tasks to corresponding Workers in Team chat
3. Continuously monitor execution progress of each Worker
4. Report task progress to users in Leader DM
5. After all subtasks complete, aggregate results and provide final report

![Collaboration Process Screenshot](https://img.alicdn.com/imgextra/i1/O1CN013g55T01vr6e61hgQ4_!!6000000006225-2-tps-2598-1646.png)

### Step 4: Human-in-the-Loop and Result Retrieval

#### Human-in-the-Loop

When issues are discovered, you can intervene immediately:

- @mention in Team chat to correct direction
- Enter Worker rooms directly to adjust details
- Send new instructions to Leader to adjust plan

#### Result Retrieval

After task completion, Leader will report in DM:

- Completed feature list
- Code repository links or file paths
- Test reports and coverage
- Issues encountered and solutions

All outputs are stored in the shared file system, accessible via MinIO, or you can ask Leader to package and send through Element.

![Result Files](https://img.alicdn.com/imgextra/i4/O1CN01QciCSc1gasNEceXux_!!6000000004159-2-tps-2388-1498.png)

---

## Configuration Reference

### Team Configuration Structure

```yaml
apiVersion: hiclaw.io/v1beta1
kind: Team
metadata:
  name: <team-name>
spec:
  description: "<team-description>"
  leader:
    name: <leader-name>
    heartbeat:
      enabled: true # Enable heartbeat
      every: 30m # Heartbeat interval
    workerIdleTimeout: 12h # Worker idle timeout
  workers:
    - name: <worker-name>
      soul: | # Worker's persona and rules
        # Worker configuration content
```

### Soul Configuration Best Practices

The Worker's `soul` field defines the Agent's identity, role, and behavioral norms:

```markdown
# <Worker Name>

## AI Identity

**You are an AI Agent, not a human.**

## Role

- Name: <name>
- Role: <role-description>
- Team: <team-name>
- Responsibilities: <responsibilities>

## Skills

- <skill-1>
- <skill-2>

## Communication

- <communication-norms>

## Security

- Never reveal credentials
- <other-security-rules>
```

---

## Best Practices

### Team Design Principles

1. **Clear Responsibilities**: Each Worker should have clear responsibility boundaries
2. **Moderate Decomposition**: Avoid over-fragmentation causing excessive coordination overhead
3. **Complementary Skills**: Workers should form complementary capabilities
4. **Resource Balance**: Allocate Worker count reasonably based on task load

### Task Assignment Tips

1. **Clear Goals**: Describe clear final objectives to Leader
2. **Step-by-step Execution**: Complex tasks should have clear execution order
3. **Set Checkpoints**: Request Leader to report progress at key nodes
4. **Timely Intervention**: Correct immediately via @mention when issues are discovered

### Performance Optimization

1. **Parallel Processing**: Design task structures that can execute in parallel
2. **Cache Reuse**: Use shared file system to reduce duplicate work
3. **Resource Monitoring**: Regularly check Worker resource usage
4. **Scale as Needed**: Dynamically adjust Worker count based on load

---

## Related Documentation

- [QwenPaw Quick Start](./quickstart)
- [QwenPaw Multi-Agent](./multi-agent)
- [QwenPaw Skills](./skills)
- [HiClaw Official Documentation](https://hiclaw.io/)

---

## Summary

QwenPaw Agent Team, through the combination of QwenPaw and HiClaw, provides powerful multi-agent collaboration capabilities for individual developers and small teams. Through proper team design and task allocation, work efficiency can be significantly improved, achieving a "one-person team."
