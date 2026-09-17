---
name: alicloud_cli
description: "阿里云 CLI 中文文档镜像检索与命令辅助：先走章节索引，再下钻正文页面，给出命令前必须有本地文档证据。"
metadata:
  {
    "builtin_skill_version": "1.1",
    "copaw":
      {
        "emoji": "🧰",
        "requires": {}
      }
  }
---

# Alicloud CLI 中文索引技能（alicloud_cli）

## 目标

把当前离线文档 `md_mirror/zh/cli` 作为唯一主源，先按“章节索引”定位范围，再定位具体页面，避免在全量目录盲搜。

## 强制工作流（速查优先，索引兜底）

1. 先使用本文件“CLI 常见用法速查”直接回答高频问题，减少读文件次数。
2. 若问题超出速查范围，再读 `references/docs_index.md` 确认章节。
3. 再进入章节目录（如 `use-cli/`、`installation-guide/`、`configure-cli/`）定位具体页面。
4. 输出命令、参数、选项时，必须来自“速查”或已命中的正文页面；找不到时明确“证据不足”。
5. 不新增需求外资源，不做“顺手增强”。

## 文档索引主链

1. `references/docs_index.md`：统一入口与章节映射（主链起点）
2. `references/cli-official-links-index.md`：官方链接索引（通过链接 ID 引用）
3. `references/links.md`：链接 ID -> 官方 URL
4. `md_mirror/zh/cli/<section>/...`：章节正文与子页面

## 章节路由（意图归类）

- 产品定义与能力概览：优先 `md_mirror/zh/cli/what-is-cli/`
- 快速起步与支持产品：优先 `md_mirror/zh/cli/quick-start/`
- 安装、升级、卸载：优先 `md_mirror/zh/cli/installation-guide/`
- 凭证、代理、自动补全：优先 `md_mirror/zh/cli/configure-cli/`
- 命令结构、参数格式、输出过滤、分页聚合、轮询：优先 `md_mirror/zh/cli/use-cli/`
- 脚本实践、跨地域迁移、容器运行：优先 `md_mirror/zh/cli/best-practices/`
- 编辑器与终端工具：优先 `md_mirror/zh/cli/common-tools/`
- 故障诊断与版本变更：优先 `md_mirror/zh/cli/cli-troubleshooting/` 和 `md_mirror/zh/cli/version-updates/`

## CLI 常见用法速查（默认优先使用）

### 帮助与发现

- 查看 CLI 总帮助：`aliyun --help`
- 查看产品帮助：`aliyun ecs --help`
- 查看 API 帮助：`aliyun ecs DescribeInstances --help`

### 配置与凭证

- 初始化/交互配置：`aliyun configure`
- 指定 AK/SK 非交互配置：
  `aliyun configure set --profile <name> --mode AK --access-key-id <ak> --access-key-secret <sk> --region <region-id>`
- 查看当前配置列表：`aliyun configure list`
- 切换配置：`aliyun configure switch --profile <name>`

### 高频查询与调用

- 查询 ECS 实例：
  `aliyun ecs DescribeInstances --RegionId <region-id>`
- 按 JSON 传复杂参数：
  `aliyun <product> <api> --SomeJsonParam '[{"key":"value"}]'`
- 仅模拟调用不落资源：
  `aliyun <product> <api> --dryrun`

### 常用全局选项

- 输出过滤/表格化：`--output cols=<...>,rows=<...>`
- 聚合分页结果：`--pager`
- 结果轮询：`--waiter expr='<jmes>' to='<target>' timeout=<sec>`
- 强制调用未收录 API：`--force --version <date>`
- 调试日志：设置 `DEBUG=sdk`（按需配合命令执行）

## 检索建议

```bash
# 1) 先在统一索引中收敛章节
rg "安装|配置|命令结构|参数格式|输出|分页|轮询|故障排查" references/docs_index.md

# 2) 在目标章节目录下检索关键词
rg "configure|credentials|proxy|auto-completion" md_mirror/zh/cli/configure-cli
rg "--output|--pager|--waiter|--dryrun|--force" md_mirror/zh/cli/use-cli
rg "install|update|uninstall" md_mirror/zh/cli/installation-guide

# 3) 若要回到官方入口，通过链接 ID 映射
rg "CLI_" references/cli-official-links-index.md references/links.md
```

## 输出要求

- 给出 CLI 命令或参数建议时，仅使用本地镜像中已命中的写法。
- 若用户要“导航/学习路径”，优先返回章节目录与推荐阅读顺序。
- 若问题过宽，先返回“候选章节 + 选择理由”，再等待用户确认细化范围。
- 对未覆盖细节，明确标注“当前离线镜像未覆盖到该信息”。
