# BASE_URL 支持完整记录（最近 5 次变更合并说明）

本文将最近 5 次与 `BASE_URL` 相关的改动整理为一份完整记录，便于回溯与发布说明。

## 1. 目标

支持以下场景：

- 后端在运行时通过环境变量 `BASE_URL` 挂载路径前缀；
- 前端 Console 在**构建后**设置 `BASE_URL` 时仍可正确访问 API、路由和静态资源；
- 兼容 `/console`、`/copaw/<agent_id>` 与 `/<custom-prefix>/console` 访问路径。

## 2. 最近 5 次改动（合并视图）

| 顺序 | 提交 | 主题 | 关键效果 |
|---|---|---|---|
| 1 | `138e3b1` | 启动时先加载持久化环境变量 | 确保 `BASE_URL` 在应用初始化早期即可生效 |
| 2 | `92121a5` | BASE_URL 前缀路由与生命周期兼容 | 避免前缀中间件影响 FastAPI 生命周期 |
| 3 | `b4fbae2` | Console 前端支持无构建期 BASE_URL 部署 | 前端运行时可推断前缀并拼接 API 路径 |
| 4 | `08e7132` | BASE_URL 前缀中间件测试 | 覆盖 HTTP/WS 前缀改写行为 |
| 5 | `62734bb` | 综合补齐（路由/静态资源） | 补齐 Console 与静态资源在前缀部署下的访问链路 |

## 3. 最终能力清单

### 后端（FastAPI）

- 支持从环境变量读取并标准化 `BASE_URL` 前缀；
- 通过前缀中间件重写请求路径并设置 `root_path`；
- Console 静态资源支持：
  - `/assets/{path}`
  - `/console/assets/{path}`
  - `${BASE_URL}/assets/{path}`（当 `BASE_URL` 配置时）

### 前端（Console）

- API 基址在运行时自动推断：
  - 优先使用注入的 `BASE_URL`；
  - 其次支持 `/<prefix>/console` 路径推断；
  - 兼容 `/copaw/<id>` 与 `/console`。
- `BrowserRouter basename` 使用与 API 相同的前缀推断策略；
- 侧边栏 Logo 使用相对路径 `logo.png`，避免根路径资源在前缀部署下 404。

## 4. 验证建议

- 启动时设置：`BASE_URL=/copaw/10001`，验证：
  - `GET /copaw/10001/api/version` 返回 200；
  - Console 页面可加载，`assets/index-*.js` 返回 200；
  - 页面内 API 请求均走 `/copaw/10001/api/*`。
- 启动时设置：`BASE_URL=/my/prefix`，并通过 `/my/prefix/console/` 访问，验证同上。

