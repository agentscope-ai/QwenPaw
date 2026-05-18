---
name: terraform-cli-setup
description: Terraform CLI 安装与初始化技能。当用户本地未安装 Terraform 时自动完成安装，确保 terraform 命令可用并能执行 init/validate。不负责 Provider 凭证配置，凭证在实际使用时由 terraform-skill 引导。
---

Category: setup

# Terraform CLI 安装与初始化

## 目标

- 检测本地是否已安装 `terraform`，未安装则自动安装
- 确保 `terraform version` 正常输出
- 引导完成 `terraform init` 初始化工作区
- 处理 Provider 下载、镜像配置等基础环境问题

> **关于 Provider 凭证配置**：各云厂商的凭证配置（AWS/Azure/GCP/阿里云等）不在本技能范围内。Provider 凭证在实际使用 Terraform 时按需配置，请参考 **terraform-skill** 中的 Provider 凭证配置引导。

## 何时触发此技能

- 用户首次使用 Terraform 相关功能
- 执行 `terraform` 命令报错 `command not found`
- `terraform init` 报 Provider 下载失败（网络/镜像问题）
- 用户主动要求安装或重新安装 Terraform
- 其他 Terraform 技能（terraform-skill）的前置依赖检查

## 完整流程

### 第 1 步：检测安装状态

```bash
which terraform 2>/dev/null || echo "NOT_INSTALLED"
```

如果未安装，进入安装流程。如果已安装，跳到第 3 步。

### 第 2 步：安装 Terraform

#### macOS (Homebrew — 推荐)

```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
```

#### macOS (手动下载)

```bash
ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64) ARCH="amd64" ;;
    arm64|aarch64) ARCH="arm64" ;;
esac
curl -fsSL "https://releases.hashicorp.com/terraform/1.14.6/terraform_1.14.6_darwin_${ARCH}.zip" -o /tmp/terraform.zip
mkdir -p ~/.local/bin
unzip -o /tmp/terraform.zip -d ~/.local/bin/
chmod +x ~/.local/bin/terraform
export PATH="$HOME/.local/bin:$PATH"
```

#### Linux (手动下载)

```bash
ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64) ARCH="amd64" ;;
    arm64|aarch64) ARCH="arm64" ;;
esac
curl -fsSL "https://releases.hashicorp.com/terraform/1.14.6/terraform_1.14.6_linux_${ARCH}.zip" -o /tmp/terraform.zip
mkdir -p ~/.local/bin
unzip -o /tmp/terraform.zip -d ~/.local/bin/
chmod +x ~/.local/bin/terraform
export PATH="$HOME/.local/bin:$PATH"
```

#### Linux (APT — Debian/Ubuntu)

```bash
sudo apt-get update && sudo apt-get install -y gnupg software-properties-common
wget -O- https://apt.releases.hashicorp.com/gpg | \
  gpg --dearmor | sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
  https://apt.releases.hashicorp.com $(lsb_release -cs) main" | \
  sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update && sudo apt-get install terraform
```

#### Linux (YUM — RHEL/CentOS/Fedora)

```bash
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://rpm.releases.hashicorp.com/RHEL/hashicorp.repo
sudo yum -y install terraform
```

安装后验证：

```bash
terraform version
```

### 第 3 步：初始化 Terraform 工作区

在有 `.tf` 文件的目录中执行：

```bash
terraform init
```

`terraform init` 会执行：

1. **初始化 Backend** — 配置状态存储（默认为本地）
2. **安装 Provider 插件** — 下载 `.tf` 中声明的 Provider
3. **下载模块** — 获取引用的远程模块
4. **创建锁文件** — 生成 `.terraform.lock.hcl` 锁定版本

常见 init 选项：

```bash
# 升级 Provider 和模块到约束范围内的最新版本
terraform init -upgrade

# 重新配置 Backend
terraform init -reconfigure

# 迁移 State 到新 Backend
terraform init -migrate-state
```

### 第 4 步：验证安装与初始化

```bash
# 检查版本
terraform version

# 检查配置文件语法（需要先 init）
terraform validate

# 格式化代码
terraform fmt -check
```

验证结果判断：

| 输出 | 含义 | 处理方式 |
|------|------|----------|
| `Terraform vX.Y.Z` | 版本正常 | 安装成功 |
| `Success! The configuration is valid.` | validate 通过 | 初始化完成 |
| `Error: Failed to query available provider packages` | Provider 下载失败 | 检查网络或配置镜像 |
| `Error: Inconsistent dependency lock file` | 锁文件不一致 | 执行 `terraform init -upgrade` |
| `Error: Module not installed` | 模块未下载 | 执行 `terraform init` |
| `Error: No valid credential sources found` | Provider 凭证缺失 | 参考 **terraform-skill** 配置凭证 |

## 自动化脚本

本技能提供 `scripts/setup_terraform.py`，用于一键检测+安装（从本技能目录执行）：

```bash
python scripts/setup_terraform.py
```

该脚本会：

1. 检测 `terraform` 是否已安装
2. 未安装则根据 OS/Arch 自动下载安装（macOS 优先用 Homebrew）
3. 输出版本信息确认安装成功

## Agent 决策指南

当你（AI Agent）执行此技能时，按以下决策树操作：

```
开始
 │
 ├── which terraform → 未找到?
 │     └── 根据操作系统自动选择最佳安装方式（无需询问用户）
 │           ├── macOS → 优先 brew install，brew 不可用则手动下载
 │           └── Linux → 优先手动下载 zip，检测到 apt/yum 则用包管理器
 │
 ├── terraform version → 正常输出?
 │     └── 是 → ✅ Terraform 已就绪
 │
 ├── 当前目录有 .tf 文件?
 │     ├── 是 → terraform init
 │     │      ├── 成功 → terraform validate
 │     │      │      ├── 成功 → ✅ 初始化完成
 │     │      │      └── 失败 → 根据错误信息自动判断修复方案并执行
 │     │      └── Provider 下载失败 → 自动配置阿里云镜像源并重试
 │     └── 否 → ✅ 安装完成，等用户创建 .tf 文件后再 init
 │
 └── 遇到 Provider 凭证错误?
       └── 引导用户参考 terraform-skill 进行凭证配置
```

### 自动决策原则

**重要**：在执行本技能时，Agent 应当**自动判断并选择最合适的方案和配置**，无需询问用户，直接执行。

#### 安装方式自动选择逻辑

| 操作系统 | 判断条件 | 自动选择 |
|----------|----------|----------|
| macOS | `which brew` 存在 | `brew install hashicorp/tap/terraform` |
| macOS | brew 不可用 | 手动下载对应架构的 zip 安装到 `~/.local/bin` |
| Linux (Debian/Ubuntu) | `which apt-get` 存在 | APT 安装 |
| Linux (RHEL/CentOS) | `which yum` 存在 | YUM 安装 |
| Linux (其他) | 无包管理器 | 手动下载 zip 安装 |

#### Provider 下载失败自动处理

当 `terraform init` 因 Provider 下载失败时，**自动配置阿里云镜像**并重试：

```bash
cat > ~/.terraformrc << 'EOF'
provider_installation {
  network_mirror {
    url = "https://mirrors.aliyun.com/terraform/"
  }
}
EOF
terraform init
```

#### init 错误自动修复

| 错误类型 | 自动修复操作 |
|----------|-------------|
| `Inconsistent dependency lock file` | 自动执行 `terraform init -upgrade` |
| `Module not installed` | 自动执行 `terraform init` |
| `Plugin reinitialization required` | 自动执行 `terraform init -upgrade` |
| `Backend initialization required` | 自动执行 `terraform init` |
| Provider 凭证错误 | 引导参考 terraform-skill 配置凭证 |

### 执行原则

1. **所有可自动判断的场景**直接由 Agent 根据环境检测结果自动选择最优方案并执行，不向用户提问
2. 安装方式根据操作系统和可用工具链自动决定
3. 错误修复根据错误类型自动匹配最佳修复策略
4. 镜像配置默认选择阿里云镜像
5. 仅在遇到需要用户提供敏感信息（如凭证）或无法自动决策的极端情况时，才以纯文本方式向用户说明

## Terraform 中国镜像配置

国内网络环境下载 Provider 可能较慢，可配置镜像。

创建或编辑 `~/.terraformrc`：

```hcl
# 阿里云镜像
provider_installation {
  network_mirror {
    url = "https://mirrors.aliyun.com/terraform/"
  }
}
```

或腾讯云镜像：

```hcl
provider_installation {
  network_mirror {
    url = "https://mirrors.tencent.com/terraform/"
  }
}
```

## 常见问题快速修复

| 问题 | 快速修复 |
|------|---------|
| `command not found: terraform` | `brew install hashicorp/tap/terraform` 或参照安装流程 |
| `Error: Failed to query available provider packages` | 检查网络连接，或配置 Terraform Registry 镜像 |
| `Error: Backend initialization required` | 执行 `terraform init` |
| `Error: Plugin reinitialization required` | 执行 `terraform init -upgrade` |
| `Error: Inconsistent dependency lock file` | 执行 `terraform init -upgrade` 更新锁文件 |
| `Error: state snapshot was created by Terraform vX.Y.Z` | 升级 Terraform 版本 |
| `Error: Module not installed` | 执行 `terraform init` 或 `terraform get` |
| Provider 下载超时 | 配置 Terraform Registry 镜像（见上方） |
| `Error: No valid credential sources found` | 此为 Provider 凭证问题，参考 **terraform-skill** |

## 配置文件位置

| 文件 | 位置 | 说明 |
|------|------|------|
| CLI 配置 | `~/.terraformrc`（macOS/Linux） | 全局 CLI 配置（镜像等） |
| Provider 缓存 | `~/.terraform.d/plugins/` | 下载的 Provider 插件缓存 |
| 工作区 Provider | `.terraform/providers/` | 当前工作区的 Provider 插件 |
| 锁文件 | `.terraform.lock.hcl` | Provider 版本锁定（应提交到 Git） |
| State 文件 | `terraform.tfstate` | 本地状态文件（不应提交到 Git） |

## 与其他技能的关系

| 技能 | 职责 |
|------|------|
| **terraform-cli-setup**（本技能） | Terraform CLI 的安装、init、镜像配置等基础环境 |
| **terraform-skill** | Terraform 实际使用：编写配置、Provider 凭证配置、模块开发、测试、CI/CD |

> **关于阿里云 ROS**：阿里云资源编排服务（ROS）没有独立 CLI 工具，直接通过 `aliyun ros <API>` 使用 aliyun-cli 调用。如需使用 ROS，请确保 aliyun-cli 已安装（参考 **alicloud_cli** 技能）。

## Interaction Tips

> **重要提示**：在使用本技能时，请遵循以下规则：
>
> 1. **自动决策优先**：安装方式、镜像选择、错误处理等场景，Agent 应根据环境检测结果自动选择最优方案并直接执行，不向用户提问
> 2. 执行过程中向用户简要说明正在做什么及原因，保持信息透明
> 3. 仅在需要用户提供无法自动获取的敏感信息（如凭证）时才向用户询问
> 4. 遇到错误时先自动尝试修复，修复失败后再向用户说明情况并提供建议

## 参考

- Terraform 官方文档：https://developer.hashicorp.com/terraform
- Terraform CLI 教程：https://developer.hashicorp.com/terraform/tutorials/cli
- Terraform 安装指南：https://developer.hashicorp.com/terraform/install
- Provider Registry：https://registry.terraform.io/
- GitHub 仓库：https://github.com/hashicorp/terraform
