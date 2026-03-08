# 构建脚本

在**项目根目录**运行。

## 构建 Wheel

```bash
bash scripts/wheel_build.sh
```

构建控制台前端并打包 Python wheel，输出：`dist/*.whl`

## 构建网站

```bash
bash scripts/website_build.sh
```

构建网站前端，输出：`website/dist/`

## 构建 Docker 镜像

```bash
bash scripts/docker_build.sh [镜像标签] [额外参数]
```

默认标签：`copaw:latest`

---

# 🐧 Linux systemd 守护进程管理

将 CoPaw 作为系统服务运行，支持开机自启、崩溃自动重启和自动更新。

## 📁 文件说明

| 文件 | 说明 |
|------|------|
| `copawd.sh` | systemd 启动脚本 |
| `copaw.service` | systemd 服务配置模板 |
| `manage-copawd.sh` | 服务管理脚本 |
| `update-copaw.sh` | 自动更新脚本 |
| `setup-cron.sh` | 定时任务配置 |
| `verify-install.sh` | 安装验证脚本 |

## 🚀 快速开始

```bash
# 1. 安装服务
sudo ./manage-copawd.sh install

# 2. 启动服务
sudo ./manage-copawd.sh start

# 3. 查看状态
./manage-copawd.sh status
```

## 📋 常用命令

### 服务管理
```bash
sudo ./manage-copawd.sh install      # 安装服务
sudo ./manage-copawd.sh start        # 启动
sudo ./manage-copawd.sh stop         # 停止
sudo ./manage-copawd.sh restart      # 重启
./manage-copawd.sh status            # 状态
./manage-copawd.sh logs              # 日志
sudo ./manage-copawd.sh uninstall    # 卸载
```

### 更新管理
```bash
./manage-copawd.sh update-check      # 检查更新
sudo ./manage-copawd.sh update       # 手动更新
./manage-copawd.sh setup-cron        # 配置定时更新
```

## 🔄 自动更新

```bash
./manage-copawd.sh setup-cron
```

配置后每天凌晨 3 点自动检查并更新，特性：
- ✅ 智能版本检测
- ✅ 优雅更新（停止→备份→更新→重启→验证）
- ✅ 配置备份（保留最近 5 个）
- ✅ 失败自动恢复

## 📊 日志查看

```bash
journalctl -u copaw.service -f       # systemd 日志
tail -f ~/.copaw/logs/copaw.log      # 应用日志
tail -f ~/.copaw/logs/copaw-update.log  # 更新日志
```

## 🆘 故障排查

```bash
# 查看详细错误
sudo journalctl -u copaw.service -n 100 --no-pager

# 验证安装
./verify-install.sh
```

## 🌍 系统兼容

- ✅ Ubuntu 22.04+ / 24.04 LTS
- ✅ Debian 12+
- ✅ 其他 systemd Linux 发行版
