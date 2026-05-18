# 文档统一入口（按当前镜像结构）

目标：把 `llms.txt` 的阿里云 CLI 文档按章节镜像到 `md_mirror/zh/cli`，检索时先章节后正文。

## 主链（固定顺序）

1. `references/docs_index.md`（统一入口与章节映射）
2. `references/cli-official-links-index.md`（官方入口索引）
3. `references/links.md`（链接 ID 到官方 URL）
4. `md_mirror/zh/cli/<section>/...`（章节正文）

## 镜像状态

- 下载总数：39
- 成功：39
- 失败：0

## 章节映射（来源于 llms.txt）

| 需求类型 | 优先路径 |
|---|---|
| 产品定义与能力概览 | `md_mirror/zh/cli/what-is-cli/` |
| 快速起步与支持产品 | `md_mirror/zh/cli/quick-start/` |
| 安装、升级、卸载 | `md_mirror/zh/cli/installation-guide/` |
| 凭证、代理、自动补全 | `md_mirror/zh/cli/configure-cli/` |
| 命令结构、参数、输出、插件 | `md_mirror/zh/cli/use-cli/` |
| 实战案例与容器化运行 | `md_mirror/zh/cli/best-practices/` |
| 编辑器与常用工具 | `md_mirror/zh/cli/common-tools/` |
| 错误排查 | `md_mirror/zh/cli/cli-troubleshooting/` |
| 版本变更追踪 | `md_mirror/zh/cli/version-updates/` |

## 固定检索命令

```bash
# 1) 先在统一索引里收敛章节
rg "安装|配置|参数格式|输出|分页|轮询|排查" references/docs_index.md

# 2) 再进入对应章节目录检索正文
rg "install|update|uninstall" md_mirror/zh/cli/installation-guide
rg "configure|credentials|proxy|auto-completion" md_mirror/zh/cli/configure-cli
rg "--output|--pager|--waiter|--dryrun|--force" md_mirror/zh/cli/use-cli
```

## 约束

- 禁止直接在整个 `md_mirror/zh/cli` 盲搜猜文件名。
- 必须先读本索引，再进入具体章节目录。
- 输出命令或参数前，必须命中正文证据。
- 若证据不足，明确标注“当前离线镜像未覆盖到该细节”。
