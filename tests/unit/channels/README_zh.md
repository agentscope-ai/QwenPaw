# 渠道测试

每个官方渠道只保留一个 `test_<channel>.py`，验证核心启停和消息收发。测试按需替换外部 SDK、网络边界，不代表真实机器人凭据或原生桌面发行版已完成验收。

公共覆盖分为：

- `test_channel_host.py`：发现、配置、宿主路由与公共生命周期。
- `../plugins/test_plugin_process.py`：worker 执行、进程归属与清理。
- `../../contract/channels/test_console_contract.py`：内置 Console 的 `BaseChannel` 契约。
- `../../channel_support/`：保留测试实际使用的公共夹具。

官方渠道插件遵循渠道协议，不需要另外建立旧式 `create_instance()` 契约套件。

## 运行

在仓库根目录、已安装项目测试依赖的环境中执行：

```sh
./scripts/check-channels.sh feishu
./scripts/check-channels.sh --changed
./scripts/check-channels.sh all
python -m pytest tests/unit/channels/test_channel_host.py tests/unit/plugins/test_plugin_process.py -q
```

选中的核心测试失败时，脚本必须失败。`--changed` 检查当前未提交及未跟踪改动；公共渠道代码变化时检查整组渠道。它不能替代仓库其他 CI。

新增覆盖放回已有渠道、宿主或进程测试文件。消息格式、参数等检查直接调用相应入口；验证资源归属、停止和恢复时才使用真实生命周期。不要恢复旧的大型夹具套件，也不要把它们搬进 helper。
