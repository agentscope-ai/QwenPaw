# 钉钉渠道插件

正式入口为 `plugin.json` 的 `entry.descriptor: "channel.json"`，运行模式为
`runner_process + shared`。插件根目录包含静态清单和唯一依赖声明
`requirements.txt`，Python 实现在 `qwenpaw_channel_dingtalk/`，子进程入口为 `qwenpaw_channel_dingtalk.driver`。
`publish: false` 和预览版本保持不变，本轮不发布制品。

## 宿主接入

`dingtalk` 永久由官方描述式插件拥有，不回退到旧内置类。Console 保留内置运行。
宿主只读取静态配置目录；插件缺失、停用、失败或缺少 SDK 时仍可编辑原配置。
配置继续使用 `DingTalkConfig`，保留原字段、默认值、扫码和凭据校验。

每个启用工作区由现有 ChannelManager / 生命周期创建宿主代理和独立 worker。
队列、会话、ACL、审批授权及 Agent 执行属于宿主；平台连接、SDK、媒体和卡片调用
属于子进程中的 Driver/platform。旧宿主平台目录及候选 `channel.py`、`plugin.py`
已经退役，没有两套连接入口。

被动发现、未启用工作区和离线预置不探测 SDK。显式安装、启用、更新、修复以及实际
运行前按真实子解释器校验依赖；只有显式安装/修复允许受控获取依赖。启动不联网安装。
失败或结果不明的发送保留恢复证据，不盲目改用另一条消息重发。
停止需确认实例连接、线程和进程退出；停用、卸载保留工作区配置、媒体和历史状态。

## 离线预置与升级

宿主从发行资源中的私有 ZIP 校验摘要，再通过现有安装事务发布到普通插件目录。
完整预设由 `qwenpaw plugins preset apply channels-full --offline` 显式记录，
后续启动执行离线源码预置；安装 extras 本身不代表已启用完整预设。
首次所有权迁移仅捕获已保存且启用的旧渠道，新轻量安装不会自动安装 SDK。
已有源码和全局停用设置保持不变；成功卸载记录的标记阻止之后启动自动恢复插件。
发行资源生成和平台打包由 C7 接入，不能把本目录存在当作发行包已包含它。

兼容读取旧 session webhook、有效期及待恢复 AI 卡片，使用原卡片 ID 完成恢复。历史数据读取位于实际 Driver/platform 中，
不需要保留旧渠道类。

## 验证边界

独立测试运行真实宿主代理、worker 和生产 Driver，只替换外部 SDK/网络边界。

```sh
python -m pytest tests/unit/channels/test_dingtalk.py -q
```

真实机器人与原生桌面运行效果尚未验证，保留为正式发布前检查。
SDK 安装体积和父子进程合计内存应使用发行制品测量，不由源码 ZIP 大小推断。
