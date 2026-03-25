# CoPaw × E2B 沙箱 — K8s 部署操作手册

本文说明如何将 CoPaw（含 E2B 沙箱集成）部署到 Kubernetes 集群，适用于已安装 [agent-runtime-controller](https://github.com/your-org/agent-runtime-controller) 的集群环境。

---

## 前提条件

| 依赖 | 说明 |
|------|------|
| Kubernetes 集群 | 已安装 `agentruntime.alibabacloud.com` CRD |
| agent-runtime-controller | 负责管理 Agent / AgentRevision / ToolServer 资源 |
| sandbox-manager | 提供 E2B 兼容 API，已部署并可从集群内访问 |
| 容器镜像仓库 | 可 push/pull 的私有或公开仓库 |
| Docker（含 buildx） | 用于构建多架构镜像 |
| kubectl | 已配置好目标集群的 kubeconfig |

---

## 目录结构

```
deploy/
├── Dockerfile.k8s       # 镜像构建文件（双阶段：前端构建 + 运行时）
├── copaw-agent.yaml     # Agent CRD 部署示例（需填写占位符后 apply）
├── config/
│   └── supervisord.conf.template
└── entrypoint.sh
```

---

## 第一步：构建并推送镜像

> 生产集群通常为 amd64 架构，需显式指定 `--platform linux/amd64`。

```bash
# 在项目根目录执行（iter-demos/copaw/）
docker buildx build --platform linux/amd64 \
  -f deploy/Dockerfile.k8s \
  -t <YOUR_REGISTRY>/copaw:latest \
  --push .
```

**说明：**

- `<YOUR_REGISTRY>` 替换为你的镜像仓库地址，例如 `registry.cn-hangzhou.aliyuncs.com/my-ns`
- 第一阶段（`console-builder`）在容器内执行 `npm ci && npm run build`，无需本地安装 Node.js
- 第二阶段安装 CoPaw Python 包及 `e2b>=1.0.0` SDK

如果需要复用 buildx 构建器：

```bash
docker buildx create --name copaw-builder --use
docker buildx inspect --bootstrap
```

---

## 第二步：配置部署 YAML

复制 `deploy/copaw-agent.yaml`，将所有 `<PLACEHOLDER>` 替换为实际值：

| 占位符 | 说明 | 示例 |
|--------|------|------|
| `<YOUR_CLUSTER_ID>` | agent-runtime 控制台中的集群 ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `<YOUR_REGISTRY>/copaw:latest` | 上一步推送的完整镜像地址 | `registry.cn-hangzhou.aliyuncs.com/my-ns/copaw:latest` |
| `<YOUR_LLM_API_KEY>` | LLM Provider 的 API Key | `sk-xxxxxxxx` |
| `<SANDBOX_MANAGER_HOST>` | sandbox-manager 在集群内的访问地址（含路径前缀） | `sandbox-manager-service.agent-runtime-system.svc.cluster.local:8000` |
| `<YOUR_E2B_API_KEY>` | sandbox-manager 接受的 Bearer Token | `<your-sandbox-manager-token>` |
| `<SANDBOX_MANAGER_DOMAIN>` | sandbox-manager 对外可达域名（用于沙箱子域名路由） | `sandbox-manager.example.com` |
| `<YOUR_COPAW_API_KEY>` | 调用 CoPaw `/api/agent/process` 的鉴权 Token | `<your-copaw-api-key>` |

**关键环境变量说明：**

```
COPAW_CONFIG_JSON   — 开启沙箱集成，template_id 须与 sandbox-manager 中注册的
                      ToolServer 名称一致（默认为 e2b-sandbox-copaw）

E2B_API_URL         — sandbox-manager 的控制面地址（E2B SDK 创建/销毁沙箱时使用）
                      格式：http://<host>/e2b

E2B_API_KEY         — sandbox-manager 的鉴权 Token

E2B_DOMAIN          — 沙箱数据面的可达域名（E2B SDK 建立 WebSocket/HTTP 连接时使用）
                      沙箱子域名格式：<sandbox_id>.<E2B_DOMAIN>

E2B_SANDBOX_URL     — 沙箱数据面 Base URL（通常与 E2B_DOMAIN 同主机）
                      格式：http://<E2B_DOMAIN>

COPAW_API_KEYS      — 逗号分隔的合法 Bearer Token 列表，用于鉴权入站请求
```

---

## 第三步：部署到集群

```bash
kubectl apply -f deploy/copaw-agent.yaml
```

查看部署状态：

```bash
# 查看 Agent 状态
kubectl get agent copaw -n default

# 查看最新 AgentRevision
kubectl get agentrevision -n default | grep copaw

# 查看 Pod 状态（等待 2/2 Running）
kubectl get pods -n default | grep copaw
```

Agent 状态变为 `Succeeded`、Pod 状态为 `2/2 Running` 即表示部署成功。

---

## 第四步：更新镜像（滚动更新）

重新构建推送镜像后，通过更新任意环境变量触发新 Revision：

```bash
# 修改 FORCE_REDEPLOY 值触发滚动更新（值任意，只需与上次不同）
kubectl patch agent copaw -n default \
  --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/env/11/value","value":"'"$(date +%s)"'"}]'
```

> 注意：`env/11` 是 `FORCE_REDEPLOY` 在 env 数组中的索引（从 0 开始），根据实际情况调整。
> 可通过 `kubectl get agent copaw -n default -o jsonpath='{.spec.template.spec.env}'` 查看当前 env 列表。

---

## 第五步：端到端验证

使用内置测试脚本验证完整调用链（CoPaw → E2B SDK → sandbox-manager → 沙箱 Pod）：

```bash
# 修改脚本头部的 COPAW_URL 和 COPAW_API_KEY 为实际值
bash scripts/test_copaw_e2b.sh
```

脚本包含 9 项测试，所有沙箱调用类测试（3-9）均采用**随机令牌验证**：每次运行生成不可预测的随机字符串，LLM 必须真实调用沙箱执行代码才能得到正确结果，无法通过直接构造答案绕过：

| # | 测试项 | 验证内容 |
|---|--------|---------|
| 1 | 健康检查 | `/api/version` 返回 200 |
| 2 | 认证校验 | 错误 Token 被拒绝（401） |
| 3 | Python 执行 | `execute_python_code` 执行并返回随机令牌 |
| 4 | Shell 执行 | `execute_shell_command` 执行并返回随机令牌 |
| 5 | Python 计算 | 执行随机大数加法，验证结果与本地计算一致 |
| 6 | 多行代码 | 多行 Python 代码执行并返回随机令牌 |
| 7 | 读取文件 | Shell 写入随机令牌到文件，`sandbox_read_file` 读回验证 |
| 8 | 写入文件 | `sandbox_write_file` 写入随机令牌，`sandbox_read_file` 读回验证 |
| 9 | 列目录 | `touch` 创建以随机令牌命名的文件，`sandbox_list_files` 列目录验证文件存在 |

全部通过输出：

```
========================================
  CoPaw → E2B 沙箱全部测试通过 ✅
========================================
```

---

## 常见问题

### Pod 处于 `1/2 Running`，readiness probe 失败

检查 readinessProbe/livenessProbe 的 `path` 配置。CoPaw 没有 `/api/health` 路由，正确路径为 `/api/version`。在 `copaw-agent.yaml` 中确认：

```yaml
readinessProbe:
  httpGet:
    path: /api/version   # ✅ 正确
    port: 8088
livenessProbe:
  httpGet:
    path: /api/version   # ✅ 正确
    port: 8088
```

### 沙箱创建失败（`SandboxCreationFailed`）

1. 确认 `E2B_API_URL` 指向 sandbox-manager，格式为 `http://<host>/e2b`（结尾不加 `/`）
2. 确认 sandbox-manager 已注册名为 `e2b-sandbox-copaw` 的 ToolServer
3. 确认 `E2B_API_KEY` 与 sandbox-manager 配置的 Token 一致

### 环境变量重复导致 AgentRevision 创建失败

```
spec.template.spec.containers[0].env[N]: Duplicate value
```

检查 Agent spec 中是否存在同名环境变量，用以下命令查看并删除重复项：

```bash
kubectl get agent copaw -n default -o jsonpath='{.spec.template.spec.env}' | python3 -m json.tool
# 找到重复项的索引 N，执行：
kubectl patch agent copaw -n default \
  --type='json' -p='[{"op":"remove","path":"/spec/template/spec/env/N"}]'
```

### 工具不可用（LLM 说工具不存在）

这通常是集群中运行的是旧版镜像导致的。重新构建推送镜像后参照「第四步」触发滚动更新。同一 session_id 的历史记忆可能也包含"工具不存在"的信息，需换一个新 session_id 重新测试。
