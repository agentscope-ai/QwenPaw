# WeldonAgent 生产部署验收清单

## 初始化

- [ ] 源码目录与数据根分离。
- [ ] `deploy/.env` 未被 Git 跟踪，数据库密码不是示例值且长度不少于 16 个字符。
- [ ] `docker compose config --quiet` 通过。
- [ ] `agent-pg` 未向宿主机发布 5432 端口。
- [ ] `agent-init` 成功完成数据库升级和基础初始化。
- [ ] `agent-app` 健康，页面可通过配置的地址访问。

## 对外展示

- [ ] 登录页、页头和聊天助手默认名称显示 WeldonAgent。
- [ ] 普通页面不展示版本号、上游 GitHub 或文档链接。
- [ ] 聊天输入区不展示宿主机绝对路径、内部智能体 ID 或 `default` 内部标识。
- [ ] 内部兼容变量和存储协议保持可用。

构建成功不能替代浏览器验收。部署后的登录页冒烟测试会检查 JavaScript
运行时异常、登录表单、重载和标签切换，不会登录或修改业务数据。

Linux（已安装测试依赖与 Playwright Chromium）：

```bash
WELDON_TEST_CONSOLE_URL=http://127.0.0.1:18089 .venv/bin/python -m pytest tests/integration/deploy/test_console_login_browser.py -q
```

Windows PowerShell：

```powershell
$env:WELDON_TEST_CONSOLE_URL = "http://127.0.0.1:18089"
& ".venv/Scripts/python.exe" -m pytest "tests/integration/deploy/test_console_login_browser.py" -q
```

测试应对准实际部署的前端构建产物；可将地址替换为服务器的内网地址。

## 多用户功能

- [ ] 管理员与普通用户登录正常。
- [ ] 智能体所有权、授权使用和协作范围隔离正确。
- [ ] 对话切换、浏览器标签切换和历史恢复无重复消息。
- [ ] 临时附件、个人知识库、产物、Agent 配置和记忆五类内容可区分访问。
- [ ] 个人知识库检索、记忆读取、产物预览和下载正常。

## 运维

- [ ] `weldon status` 和 `weldon logs` 可用。
- [ ] 完整备份包含数据库、工作数据、密钥和校验清单。
- [ ] 恢复会拒绝非空文件目录或非空数据库。
- [ ] 在隔离的新数据根完成一次恢复演练，并通过业务验证。
- [ ] 仓库审计报告中业务数据未被建议自动删除。
