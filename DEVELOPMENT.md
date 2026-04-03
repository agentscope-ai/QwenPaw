# CoPaw 开发与部署指南

## 目录

- [快速开始](#快速开始)
- [本地开发](#本地开发)
- [生产部署](#生产部署)
- [环境差异](#环境差异)
- [常见问题](#常见问题)

## 快速开始

### 前置要求

- Docker & Docker Compose
- Node.js 18+ (仅本地开发需要)
- Python 3.10+ (仅本地开发需要)

### 使用 Docker Compose 启动（推荐）

```bash
# 1. 克隆仓库
git clone <repository-url>
cd CoPaw

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少设置 COPAW_AUTH_ENABLED=true

# 3. 构建前端
cd console
npm install
npm run build
cd ..

# 4. 启动服务
docker compose up -d

# 5. 访问应用
# 浏览器打开: http://localhost/console/
# 首次访问会提示注册管理员账户
```

### 验证部署

```bash
# 检查服务状态
docker compose ps

# 检查健康状态
curl http://localhost/api/health/detailed

# 检查认证配置
curl http://localhost/api/auth/status
# 应返回: {"enabled": true, "has_users": ...}
```

## 本地开发

### 方式一：完全本地开发（推荐）

适用于需要频繁修改后端代码的场景。

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. 安装依赖
pip install -e ".[supabase]"

# 3. 配置环境变量
export COPAW_AUTH_ENABLED=true
export COPAW_WORKING_DIR=./working
export COPAW_SECRET_DIR=./working.secret

# 4. 启动后端
copaw app --host 0.0.0.0 --port 8088 --reload

# 5. 启动前端（新终端）
cd console
npm run dev
# 访问: http://localhost:5173/console/
```

### 方式二：混合开发（后端本地 + 前端容器）

适用于只需修改后端代码的场景，使用 `backend-dev.sh` 脚本。

```bash
# 1. 确保前端已构建
cd console && npm run build && cd ..

# 2. 启动 Docker Compose（nginx + console）
docker compose up -d nginx

# 3. 运行开发脚本（会停止 Docker 后端，启动本地后端）
./scripts/backend-dev.sh

# 访问: http://localhost/console/
# 后端支持热重载，修改代码会自动重启
```

**脚本做了什么：**
1. 停止 Docker 的 copaw 容器
2. 更新 nginx 配置，将 API 请求代理到宿主机 `172.x.x.x:8088`
3. 使用 Docker volumes 的数据目录（保持数据一致性）
4. 启动本地后端，支持热重载

### 前端开发

```bash
cd console

# 开发模式（带热重载）
npm run dev

# 构建生产版本
npm run build

# 预览构建结果
npm run preview

# 类型检查
npm run type-check

# 代码检查
npm run lint
```

**重要配置：**

`console/vite.config.ts`:
```typescript
export default defineConfig({
  base: '/console/',  // 必须与 nginx location 路径一致
  // ...
})
```

## 生产部署

### Docker Compose 部署

```bash
# 1. 准备环境
cp .env.example .env
# 编辑 .env，设置必要的环境变量

# 2. 构建前端
cd console && npm run build && cd ..

# 3. 验证构建
./scripts/verify-build.sh

# 4. 启动服务
docker compose up -d

# 5. 查看日志
docker compose logs -f

# 6. 停止服务
docker compose down
```

### Kubernetes 部署

```yaml
# deployment.yaml 示例
apiVersion: apps/v1
kind: Deployment
metadata:
  name: copaw
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: copaw
        image: agentscope/copaw:latest
        env:
        - name: COPAW_AUTH_ENABLED
          value: "true"
        ports:
        - containerPort: 8088
        livenessProbe:
          httpGet:
            path: /api/health/live
            port: 8088
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /api/health/ready
            port: 8088
          initialDelaySeconds: 5
          periodSeconds: 5
```

## 环境差异

### 本地开发 vs 生产部署

| 特性 | 本地开发 | 生产部署 |
|------|---------|---------|
| **前端** | Vite dev server (HMR) | 静态文件 (nginx) |
| **后端** | 本地进程 (热重载) | Docker 容器 |
| **数据库** | 本地文件 | Docker volume |
| **Nginx** | 代理到 host-gateway | 代理到容器 |
| **认证** | 可选 | 必须启用 |
| **日志** | 控制台输出 | Docker logs |

### 配置文件差异

**nginx.conf** (生产):
```nginx
upstream backend {
    server copaw:8088;  # 容器名
}
```

**nginx.dev-local.conf** (开发):
```nginx
upstream backend {
    server host-gateway:8088;  # 宿主机
}
```

### 环境变量

| 变量 | 开发环境 | 生产环境 | 说明 |
|------|---------|---------|------|
| `COPAW_AUTH_ENABLED` | true | true | 认证开关 |
| `COPAW_WORKING_DIR` | ./working | /app/working | 工作目录 |
| `COPAW_SECRET_DIR` | ./working.secret | /app/working.secret | 密钥目录 |
| `DEBUG` | true | false | 调试模式 |
| `COPAW_LOG_LEVEL` | debug | info | 日志级别 |

## 常见问题

### 1. 无需登录就能访问

**症状：** 访问 `/console/` 直接跳转到聊天页面，不显示登录页。

**排查：**
```bash
# 检查认证状态
curl http://localhost/api/auth/status
# 应返回: {"enabled": true, ...}

# 检查健康状态
curl http://localhost/api/health/detailed
# 查看 auth.enabled 和 auth.status
```

**解决：**
```bash
# 确保环境变量已设置
docker exec copaw env | grep COPAW_AUTH_ENABLED

# 如果未设置，更新 docker-compose.yml
# 添加: COPAW_AUTH_ENABLED=true
docker compose up -d copaw
```

### 2. 前端资源加载失败

**症状：** 浏览器控制台报错 `Failed to load module script` 或 `MIME type error`。

**排查：**
```bash
# 检查 index.html 中的资源路径
cat console/dist/index.html | grep "src="
# 应该看到: /console/assets/...

# 检查 vite.config.ts
grep "base:" console/vite.config.ts
# 应该是: base: '/console/'
```

**解决：**
```bash
# 重新构建前端
cd console
npm run build
cd ..

# 验证构建
./scripts/verify-build.sh

# 重启 nginx
docker compose restart nginx
```

### 3. API 请求返回 502

**症状：** 前端可以访问，但 API 请求失败。

**排查：**
```bash
# 检查后端容器状态
docker compose ps copaw

# 查看后端日志
docker compose logs copaw

# 测试后端连接
curl http://localhost:8088/api/health/
```

**解决：**
```bash
# 重启后端
docker compose restart copaw

# 或查看详细错误
docker compose logs -f copaw
```

### 4. backend-dev.sh 脚本失败

**症状：** 运行 `./scripts/backend-dev.sh` 报错。

**常见原因：**
- 端口 8088 被占用
- nginx 容器未运行
- 虚拟环境未激活

**解决：**
```bash
# 检查端口占用
lsof -ti:8088

# 杀掉占用进程
kill $(lsof -ti:8088)

# 确保 nginx 运行
docker compose up -d nginx

# 重新运行脚本
./scripts/backend-dev.sh
```

### 5. Docker 网络问题

**症状：** 容器间无法通信。

**排查：**
```bash
# 检查网络
docker network ls | grep copaw

# 检查容器网络配置
docker inspect copaw | grep -A 10 Networks

# 测试容器间连接
docker exec copaw-nginx ping -c 2 copaw
```

**解决：**
```bash
# 重建网络
docker compose down
docker compose up -d
```

## 工具脚本

### verify-build.sh

验证构建配置是否正确：

```bash
./scripts/verify-build.sh
```

检查项：
- ✓ Console dist 是否存在
- ✓ 资源路径是否包含 `/console/` 前缀
- ✓ Nginx 配置是否正确
- ✓ Docker Compose 配置是否包含必要的环境变量

### generate-nginx-config.sh

从模板生成 nginx 配置：

```bash
# 使用默认值
./scripts/generate-nginx-config.sh

# 使用自定义值
BACKEND_HOST=custom-backend \
BACKEND_PORT=9000 \
./scripts/generate-nginx-config.sh
```

### backend-dev.sh

启动本地开发环境：

```bash
./scripts/backend-dev.sh
```

按 `Ctrl+C` 停止后端，脚本会自动清理。

## 最佳实践

### 1. 开发流程

```bash
# 1. 创建功能分支
git checkout -b feature/my-feature

# 2. 本地开发
./scripts/backend-dev.sh  # 或使用完全本地开发

# 3. 测试
npm run test  # 前端测试
pytest        # 后端测试

# 4. 构建验证
cd console && npm run build && cd ..
./scripts/verify-build.sh

# 5. 提交代码
git add .
git commit -m "feat: add my feature"
git push origin feature/my-feature
```

### 2. 环境变量管理

- **开发环境：** 使用 `.env` 文件（不提交到 git）
- **生产环境：** 使用 Docker secrets 或 K8s ConfigMap/Secret
- **CI/CD：** 使用 GitHub Secrets 或 GitLab Variables

### 3. 日志管理

```bash
# 查看实时日志
docker compose logs -f

# 查看特定服务日志
docker compose logs -f copaw

# 导出日志
docker compose logs > logs.txt
```

### 4. 数据备份

```bash
# 备份 Docker volumes
docker run --rm \
  -v copaw-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/copaw-data-backup.tar.gz /data

# 恢复
docker run --rm \
  -v copaw-data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/copaw-data-backup.tar.gz -C /
```

## 参考资料

- [Vite 配置文档](https://vitejs.dev/config/)
- [Nginx 配置文档](https://nginx.org/en/docs/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)

## 获取帮助

- GitHub Issues: <repository-url>/issues
- 文档: <docs-url>
- 社区: <community-url>
