# CoPaw 开发环境部署指南

## 架构概述

CoPaw 采用微前端架构，通过 Nginx 反向代理实现统一网关：

```
https://copaw-comokiki.gd.ddnsto.com
    ↓
Nginx (80端口)
    ├─ /              → Website 应用 (营销、文档、登录)
    ├─ /console/*     → Console 应用 (管理控制台)
    └─ /api/*         → Backend 服务 (后端 API)
```

## 快速开始

### 1. 环境准备

确保已安装：
- Docker & Docker Compose
- Node.js 20+（本地开发可选）

### 2. 配置环境变量

根目录的 `.env` 文件已自动创建，包含 Supabase 配置：

```bash
VITE_SUPABASE_URL=https://mpegtqotbyiayvuwqtlu.supabase.co
VITE_SUPABASE_ANON_KEY=sb_publishable_J_GHWBaMz9Xe-6waK2shJw_Uyi-if6t
```

### 3. 启动服务

```bash
# 一键启动所有服务
./scripts/dev-start.sh
```

启动后可访问：
- Website: `http://localhost` 或 `http://192.168.31.210`
- Console: `http://localhost/console/chat`
- Backend: `http://localhost:8088`
- 外网: `https://copaw-comokiki.gd.ddnsto.com`

### 4. 停止服务

```bash
./scripts/dev-stop.sh
```

## 服务说明

### Nginx (端口 80)
- 统一网关，处理所有请求路由
- 配置文件: `nginx/nginx.conf`

### Website (内部端口 5174)
- 营销网站、文档、登录页面
- 路由: `/`, `/docs`, `/login`, `/auth/callback`
- 技术栈: React + Vite + Supabase Auth

### Console (内部端口 5173)
- 管理控制台和聊天界面
- 路由: `/console/*`（所有路由带 `/console` 前缀）
- 技术栈: React + Vite + Ant Design + Supabase Auth

### Backend (端口 8088)
- 后端 API 服务
- 通过 `/api/*` 路径访问

## 认证流程

1. 用户访问 `https://copaw-comokiki.gd.ddnsto.com` → Website 首页
2. 点击登录 → `/login` 页面
3. 使用 Google/Email 登录（Supabase）
4. 登录成功 → 自动跳转到 `/console/chat`
5. Console 应用检查 Supabase 认证状态
6. 认证通过 → 显示聊天界面

## 开发说明

### 本地开发（不使用 Docker）

如果需要本地开发单个应用：

**Website:**
```bash
cd website
npm install
npm run dev  # 访问 http://localhost:5174
```

**Console:**
```bash
cd console
npm install
npm run dev  # 访问 http://localhost:5173
```

注意：本地开发时需要手动配置 Nginx 或修改 API 调用地址。

### 查看日志

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f nginx
docker-compose logs -f console
docker-compose logs -f website
docker-compose logs -f copaw
```

### 重新构建

如果修改了 Dockerfile 或依赖：

```bash
docker-compose build
docker-compose up -d
```

## 故障排查

### 1. 端口冲突

如果 80 端口被占用：
```bash
# 查看占用端口的进程
sudo lsof -i :80
# 或
sudo netstat -tulpn | grep :80
```

### 2. 认证失败

检查 Supabase 配置：
- 确认 `.env` 文件中的 `VITE_SUPABASE_URL` 和 `VITE_SUPABASE_ANON_KEY` 正确
- 在 Supabase 控制台检查 OAuth 回调 URL 配置

### 3. 路由 404

检查 Nginx 配置：
```bash
docker exec copaw-nginx nginx -t  # 测试配置
docker-compose restart nginx      # 重启 Nginx
```

### 4. 容器无法启动

```bash
# 查看容器状态
docker-compose ps

# 查看详细错误
docker-compose logs <service-name>
```

## ddnsto 配置

确保 ddnsto 配置正确：
1. 域名: `https://copaw-comokiki.gd.ddnsto.com:443`
2. 内网地址: `http://192.168.31.210:80`（指向 Nginx）
3. 协议: HTTPS → HTTP

## 生产部署

生产环境建议：
1. 使用生产构建（`npm run build`）
2. 配置 SSL 证书（Let's Encrypt）
3. 启用 Nginx 缓存和压缩
4. 配置日志轮转
5. 设置健康检查和监控

## 技术支持

如有问题，请查看：
- 项目文档: `/docs`
- GitHub Issues: [项目地址]
