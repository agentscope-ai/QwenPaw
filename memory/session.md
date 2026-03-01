# 当前工作会话记录

## 任务背景
用户请求分析代码库并创建 CLAUDE.md 文件，用于指导未来的 Claude Code 实例在此仓库中工作。

## 已完成的工作

### 1. 创建 CLAUDE.md ✅
- 位置：`D:\porject\CoPaw\CLAUDE.md`
- 内容包含：
  - 快速命令（安装、测试、构建等）
  - 代码架构说明（目录结构、核心模块）
  - 配置系统说明
  - 扩展开发指南（渠道、技能、LLM 提供者）
  - 代码规范和测试说明

### 2. 安装依赖 ✅
- `pip install -e . --no-deps` - 项目已安装（可编辑模式）
- 完整依赖安装因 Windows 长路径限制失败，需要：
  - 启用 Windows 长路径支持
  - 重新运行 `pip install -e ".[dev]"`

### 3. 配置 pre-commit ✅
- `pip install pre-commit` - 已安装
- `python -m pre_commit install` - Git hooks 已配置
- 安装位置：`.git\hooks\pre-commit`

### 4. 安装 pytest 依赖 ✅
- pytest、pytest-asyncio、pytest-cov 均已安装

## 待办事项

### 高优先级
1. **启用 Windows 长路径支持**
   - 以管理员身份运行 PowerShell
   - 执行：`New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force`
   - 重启计算机

2. **安装完整依赖**
   - 启用长路径后运行：`pip install -e ".[dev]"`

### 可选任务
- 构建前端控制台：`cd console && npm ci && npm run build`
- 运行测试验证：`pytest`

## 项目关键信息

### 项目结构
- 类型：个人 AI 助手（多聊天渠道支持）
- Python 包名：`copaw`
- 主要依赖：agentscope、agentscope-runtime、discord-py、dingtalk-stream 等

### 核心命令
```bash
copaw init --defaults   # 初始化配置
copaw app               # 启动服务（默认端口 8088）
pytest                  # 运行测试
```

### 工作目录
- 默认：`~/.copaw`
- 可通过 `COPAW_WORKING_DIR` 环境变量覆盖

### 环境要求
- Python: 3.10 ~ 3.13
- Node.js: 用于构建前端控制台
