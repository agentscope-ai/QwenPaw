# QwenPaw 7 月质量计划 Review：单测执行与推进说明

## 一、先校正最新基线

本地已拉到最新 `origin/main`。现在计划不能再按旧基线写。

| 项目 | 当前状态 |
|---|---|
| 后端 `chats` 单测 | 已有：`tests/unit/app/chats/`，5 个测试文件 |
| 后端 `crons` 单测 | 已有：`tests/unit/app/crons/`，4 个测试文件 |
| 前端测试文件 | `console/src` 下 103 个 `.test.ts/.test.tsx` |
| CI workflow | 22 个 |
| CodeQL | 暂无 |
| 覆盖率门槛 | `fail_under = 30` |

所以计划口径应从：

> chats / crons / inbox / approvals / channels 五个模块从 0 补单测

修正为：

> chats / crons 已经完成第一批单测打样；7 月复用这个模式继续补 inbox / approvals / channels，并把真实 bug 固化成回归测试，最后把覆盖率门槛从 30 提到 45。

这点很重要：它说明计划不是拍脑袋，而是沿着已经合并的 PR 继续推进。

---

## 二、单测到底怎么执行

单测不是“上线前跑一下”，而是一条持续工作的质量流水线。

### 1. 本地开发时跑：快速定位

开发者改了哪个模块，就只跑对应模块的测试。

```bash
python -m pytest tests/unit/app/chats -q
python -m pytest tests/unit/app/crons -q
python -m pytest tests/unit/app/inbox -q
```

前端类似：

```bash
cd console
npm run test:run -- src/api/modules/backup.test.ts
```

目的：10 秒内知道“我刚改的模块有没有坏”。

---

### 2. PR 上跑：拦住明显回归

提交 PR 后，CI 跑完整单测：

```bash
python -m pytest tests/unit/ -v --tb=short
```

前端跑：

```bash
cd console
npm run test:run
```

目的：防止一个 PR 改了 A，顺手把 B 搞坏。

---

### 3. 覆盖率跑：防止“写了很多代码但没测”

当前门槛：

```toml
fail_under = 30
```

7 月目标建议：

```toml
fail_under = 45
```

但不要马上硬改。正确顺序是：

1. 先补 `inbox / approvals / channels` 单测。
2. 跑覆盖率，看自然提升到多少。
3. 稳定超过 45 后，再把门槛改成 45。
4. CI 开始强制执行。

为什么不直接拉到 70？

因为会逼大家写“为了覆盖率而覆盖率”的假测试。45 是第一阶段务实目标：主路径被测到，但不把团队压爆。

---

## 三、7 月计划应该怎么推进

### 第 1 周：接上 chats / crons 的模板

已经合并的 `chats` / `crons` 是样板。后续照这个结构补：

```text
tests/unit/app/inbox/
tests/unit/app/approvals/
tests/unit/app/channels/
```

每个模块先补三类测试：

| 类型 | 测什么 |
|---|---|
| model/schema 测试 | 字段、默认值、非法参数 |
| service/repo 测试 | CRUD、状态流转、异常分支 |
| router/API 测试 | 请求参数、返回值、错误码 |

目标不是一次写满，而是先把测试骨架立起来。

---

### 第 2 周：把真实 bug 变成回归测试

不要只追覆盖率，要把线上真实疼点固化成测试。

优先 5 个：

| Issue | 为什么优先 | 要补什么测试 |
|---|---|---|
| #5379 安装后 Internal Server Error | 新用户第一步就炸 | 安装冒烟测试 |
| #5717 malformed tool-call 死循环 | agent 卡死 | runtime 回归测试 |
| #5411 LLM acquire timeout 挂起 | 空闲后不可用 | timeout 注入测试 |
| #5479 大会话 >500KB 打开失败 | 前端可用性问题 | 大 payload 渲染测试 |
| #5090 rm 防护被绕过 | 安全红线 | tool guard 绕过测试 |

对官方同学可以这样说：

> 我们不是抽象地补测试，而是把真实 bug 固化成回归测试。以后同类问题再出现，CI 会直接红。

---

### 第 3 周：接入质量护栏

#### real-behavior-proof

外部 PR 必须写清：

- 解决什么问题
- 用什么证据证明改对了

前 2 周只 warn，不 block；第 3 周再严格拦截。

作用：减少“我以为改对了”的 PR，降低 reviewer 猜谜成本。

#### CodeQL

CodeQL 是 GitHub 原生安全扫描。

普通 lint 像拼写检查，只看一行代码写得对不对。CodeQL 像侦探，能追踪：

> 用户输入 → 经过几个函数 → 最后流到危险操作

比如 #5090 这种“rm 防护被绕过”，就属于 CodeQL 有价值的场景。

建议先做 4 个分片 dry-run：

```text
auth
db-llm-provider
api-route
frontend
```

2 周只看结果，不拦 PR。噪音清理后，再只拦新增高危问题。

---

### 第 4 周：验收

7 月底验收标准：

| 指标 | 目标 |
|---|---|
| 后端覆盖率门槛 | 30 → 45 |
| 新增后端模块单测 | `inbox / approvals / channels` 至少有骨架 |
| P0 bug | 至少关闭 5 个，并带回归测试 |
| real-behavior-proof | warn-only 跑完，准备转 block |
| CodeQL | 4 分片 dry-run 跑通 |
| 前端测试 | 补 #5479 大 payload 回归测试 |

---

## 四、计划 review 结论

这个计划可以继续推进，但口径要改准。

不要说：

> 我们要从 0 开始补 chats/crons/inbox/approvals/channels。

要说：

> chats/crons 已经通过 #5422/#5423 完成第一批单测打样。7 月复用这个模式继续补 inbox/approvals/channels，同时把真实 bug 写成回归测试，并把覆盖率门槛从 30 提到 45。

这句话更稳，也更容易说服官方同学。

---

## 五、对官方同学的一句话版本

> 7 月质量计划不是单纯堆测试数量，而是沿着已合并的 chats/crons 单测模板，继续补 inbox、approvals、channels 三个核心模块；同时把 #5379、#5717、#5411、#5479、#5090 这类真实 bug 固化成回归测试。等覆盖率自然提升后，把门槛从 30 提到 45。配套接入 real-behavior-proof 和 CodeQL，前者提升 PR 说明质量，后者补安全扫描护栏。这样既能止血，也能防止同类问题反复出现。
