# QwenPaw 本地开发环境配置教程

本文面向需要从源码二次开发的同学，按顺序完成：前置准备 → 克隆仓库 → 配置前端 → 配置后端 → 启动前端 → 启动后端。

开发联调时通常需要同时跑两个进程：

| 进程 | 命令 | 默认地址 |
|------|------|----------|
| 后端 | `qwenpaw app` | http://127.0.0.1:8088/ |
| 前端（Vite） | `npm run dev`（在 `console/`） | http://127.0.0.1:5173/ |

前端开发服务器会把 API 请求代理到后端 `8088` 端口。

---

## 1. 前置准备

### 1.1 环境要求

| 工具 | 版本要求 | 说明 |
|------|----------|------|
| Git | 任意较新版本 | 克隆与提交代码 |
| Python | **3.10 ~ 3.13**（`<3.14`） | 后端运行时 |
| Node.js | 建议 LTS（18+ / 20+） | 前端构建与热更新 |
| npm | 随 Node.js 安装 | 安装 `console` 依赖 |
| IDE（可选） | PyCharm / IntelliJ IDEA | 配置运行配置一键启动 |

### 1.2 检查环境

在终端执行：

```bash
git --version
python --version
node --version
npm --version
```

Windows PowerShell 若 `python` 不可用，可试 `py --version`。

### 1.3 建议工具

- 使用虚拟环境（`venv` / `uv`）隔离 Python 依赖，避免污染系统 Python。
- Windows 推荐在 PowerShell 或 IDEA/PyCharm 内置终端中操作。

---

## 2. 克隆仓库

### 2.1 克隆官方仓库

```bash
git clone https://github.com/agentscope-ai/QwenPaw.git
cd QwenPaw
```

若你已有自己的 Fork：

```bash
git clone https://github.com/<your-username>/QwenPaw.git
cd QwenPaw
```

### 2.2 用 IDE 打开项目

- **PyCharm**：Open → 选择仓库根目录 `QwenPaw`
- **IntelliJ IDEA**：Open → 选择仓库根目录；如需 npm 运行配置，请启用 **JavaScript and TypeScript** 插件（Settings → Plugins）

下文以仓库根目录为 `D:\code\python\QwenPaw` 举例，请按本机路径替换。

---

## 3. 配置前端

前端工程位于 `console/`，技术栈为 React + Vite + TypeScript。

### 3.1 安装依赖

```bash
cd console
npm ci
```

`npm ci` 会按 lockfile 安装，适合首次配置与 CI。若无 lock 冲突，可改用 `npm install`。

### 3.2 确认开发脚本

`console/package.json` 中常用脚本：

| 脚本 | 作用 |
|------|------|
| `npm run dev` | 启动 Vite 开发服务器（热更新） |
| `npm run build` | 构建生产静态资源 |
| `npm run lint` | ESLint 检查 |

开发联调只需 `npm run dev`。若只跑后端、由后端托管静态页，则需要先 `npm run build` 并把产物拷到包内（见 README「从源码安装」）；日常改前端时不必每次 build。

### 3.3 代理说明（了解即可）

`console/vite.config.ts` 中开发服务器默认：

- 端口：`5173`
- API 代理目标：`http://localhost:8088`

因此联调时请先（或同时）启动后端，否则页面能开但接口会失败。

---

## 4. 配置后端

后端为 Python 包 `qwenpaw`，源码在 `src/qwenpaw/`。

### 4.1 创建并激活虚拟环境

在仓库根目录执行：

**Windows (PowerShell)：**

```powershell
cd D:\code\python\QwenPaw
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux：**

```bash
cd QwenPaw
python3 -m venv .venv
source .venv/bin/activate
```

在 PyCharm / IDEA 中：

1. Settings → Project → Python Interpreter
2. 选择 Add Interpreter → Existing / New，指向 `.venv\Scripts\python.exe`（Windows）或 `.venv/bin/python`

### 4.2 以可编辑模式安装项目

开发建议安装完整依赖（含测试与常用扩展）：

```bash
# 确保当前在仓库根目录，且已激活 .venv
pip install -U pip
pip install -e ".[dev,full]"
```

仅最小可运行：

```bash
pip install -e .
```

### 4.3 初始化工作区配置

首次启动前执行一次：

```bash
qwenpaw init --defaults
```

交互式初始化可用 `qwenpaw init`。

### 4.4 依赖兼容提示（重要）

当前代码仍使用 `agent-client-protocol` 中的 `SetSessionModelResponse`，而 **0.11.x** 已移除该类型。若启动时报：

```text
ImportError: cannot import name 'SetSessionModelResponse' from 'acp'
```

请将依赖锁定到 0.10.x：

```bash
pip install "agent-client-protocol==0.10.1"
```
或在 `pyproject.toml` 中约束为 `"agent-client-protocol>=0.9.0,<0.11"` 后重新安装。

### 4.5 验证后端可导入

```bash
python -c "from qwenpaw.app._app import app; print('OK')"
```

能打印 `OK` 即说明 Python 依赖与包安装基本正确。

---

## 5. 启动前端

### 5.1 命令行启动

```bash
cd console
npm run dev
```

成功后终端会提示本地地址，一般为：

```text
http://127.0.0.1:5173/
```

浏览器打开该地址即可访问开发态 Console。

### 5.2 在 IntelliJ IDEA / PyCharm 配置运行

1. **Run → Edit Configurations…**
2. 点 **+** → 选 **npm**
3. 按下面填写：

| 项 | 值 |
|----|-----|
| Name | `QwenPaw Console` |
| package.json | `<仓库根>/console/package.json` |
| Command | `run` |
| Scripts | `dev` |
| Node interpreter | 本机 Node |

若没有 **npm** 配置类型：

1. **+** → **Shell Script**
2. Script text：`npm run dev`（Windows 可用 `npm.cmd run dev`）
3. Working directory：`<仓库根>/console`

---

## 6. 启动后端

### 6.1 命令行启动

在仓库根目录、已激活虚拟环境的前提下：

```bash
# 日常启动
qwenpaw app

# 开发推荐：调试日志 + 热重载
qwenpaw app --log-level debug --reload
```

等价写法：

```bash
python -m qwenpaw app --log-level debug --reload
```

默认监听：

```text
http://127.0.0.1:8088/
```

仅后端、使用已构建静态前端时，可直接访问 `8088`。前后端分离开发时，建议浏览器用前端的 `5173`。

### 6.2 在 PyCharm / IDEA 配置运行

1. **Run → Edit Configurations…**
2. 点 **+** → 选 **Python**
3. 推荐使用 **Module name** 方式：

| 项 | 值 |
|----|-----|
| Name | `QwenPaw Backend` |
| Module name | `qwenpaw` |
| Parameters | `app --log-level debug --reload` |
| Working directory | 仓库根目录（如 `D:\code\python\QwenPaw`） |
| Python interpreter | 项目 `.venv` |

期望命令类似：

```text
.venv\Scripts\python.exe -m qwenpaw app --log-level debug --reload
```

**常见错误：不要把 `python.exe` 填进 Script path。**  
否则会出现双重 `python.exe`，并报：

```text
SyntaxError: Non-UTF-8 code starting with '\x90' in file ...\python.exe
```

正确做法：解释器栏已选 `.venv` 的 Python；运行目标用 **Module name = `qwenpaw`**，或 Script path 指向 `.venv\Scripts\qwenpaw.exe`（Parameters 仍为 `app ...`）。

### 6.3 前后端一键启动（可选）

1. **+** → **Compound**
2. Name：`QwenPaw Full Stack`
3. 勾选 `QwenPaw Backend` 与 `QwenPaw Console`
4. 一次运行即可同时启动

---

## 7. 启动后检查清单

1. 后端日志无 Traceback，能看到 Uvicorn / 应用启动信息。
2. 前端 Vite 已 ready，浏览器能打开 `http://127.0.0.1:5173/`。
3. 打开 Console → **设置 → 模型**，配置云端 API Key 或本地模型（Ollama / LM Studio 等）。
4. 在聊天页发送一条消息，确认前后端联通。

更多模型配置见官方文档：[Models](https://qwenpaw.agentscope.io/docs/models)。

---

## 8. 常见问题

### Q1：前端页面能开，接口全失败？

后端未启动，或未监听 `8088`。先启动 `qwenpaw app`，再刷新前端。

### Q2：`ImportError: SetSessionModelResponse`？

见 [4.4](#44-依赖兼容提示重要)，将 `agent-client-protocol` 降到 `0.10.1`。

### Q3：更新代码后前端/后端异常？

```bash
# 后端
pip install -e ".[dev,full]"

# 前端
cd console && npm ci
```

大版本更新后，按 README 提示必要时重建静态资源并清浏览器缓存（`Ctrl+Shift+R`）。

### Q4：只想快速体验、不改前端？

可只装后端并构建一次静态 Console（见 README「从源码安装」），然后只运行 `qwenpaw app`，访问 `http://127.0.0.1:8088/`。

---

## 9. 相关文档

- 项目结构与二次开发入口：[DEVELOPER_ONBOARDING_zh.md](./DEVELOPER_ONBOARDING_zh.md)
- 中文 README 安装说明：[README_zh.md](./README_zh.md)
- 官方文档站：https://qwenpaw.agentscope.io/
