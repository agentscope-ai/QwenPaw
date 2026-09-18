# Hub 模型监听网络契约

## 目标

修复 PR #7779 review 指出的模型路由、准入、同步 I/O 和日志问题，同时取消模型端口的全网卡监听。网络地址由 provisioner 提供，不在 Hub、listener 或配置中硬编码 Docker 子网，也不为本分支新增格式保留兼容接口。

## 模块职责

`provisioner.py` 定义不可变的 `RuntimeModelNetwork`：

- `bind_host`：Hub 应绑定的宿主机 IPv4 地址。
- `runtime_host`：Runtime 访问 Hub 使用的地址或域名。
- `url(port)`：在监听端口确定后生成 Runtime 使用的 URL。

`RuntimeProvisioner.model_network()` 返回该描述，默认实现服务于本机进程。隔离后端覆盖该方法。`DockerRuntimeProvisioner` 负责 Docker API 探测及桌面系统网络差异。

| 后端                                   | bind_host 来源                                                                     | runtime_host 来源                |
| -------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------- |
| Local                                  | 标准 IPv4 回环地址                                                                 | 同一回环地址                     |
| Docker Desktop、macOS／Windows 容器 VM | 标准 IPv4 回环地址                                                                 | VM 提供的 `host.docker.internal` |
| 原生 Linux Docker Engine               | Docker API：`networks.get("bridge").attrs["IPAM"]["Config"]` 中的私有 IPv4 Gateway | 同一个探测结果                   |

不假定 bridge 名为 `docker0`，不假定网关是 `172.17.0.1`，不使用可能与监听地址不同的 daemon `host-gateway` 覆盖值。IPv6-only、不可绑定的网关、缺失的 DNS 或远程 Engine 不通过回退到通配地址解决；探测、绑定或实例内连通性验证会明确失败。

`control_app.py` 只编排生命周期：在线程池读取所有可用 provisioner 的描述，保存本次 Hub 生命周期的快照，将去重的 `bind_host` 集合传给 listener。配置中切换已可用的 Local／Docker 后端不重新探测地址。为实例注入模型 URL 时复用对应快照，避免监听时与启动实例时分别探测造成不一致。底层 Docker 网络变更后重启 Hub。

`ModelListener` 不导入 Docker、Colima 或操作系统判断。它校验地址，拒绝通配、组播和公网地址，在各明确地址绑定同一个持久化端口，并管理共享 gateway 的服务生命周期。没有可用后端时不启动模型监听器，但管理面仍可用。任一绑定失败即关闭已创建的 socket 并回滚端口写入，不留下半启动的服务。

## 相关安全边界

- 控制端口不挂载 runtime 模型路由；通用 Runtime 代理也拒绝转发这些路径。
- 模型端口只接受模型 capability，不接受 Hub 登录 token，不开放管理员接口。
- 通用 Runtime API 不检查模型 capability；已运行的旧实例可继续使用个人供应商。通过正常重启注入组织模型凭证，不热补旧进程。
- 管理员模型测试仍使用同一个 gateway，但不因此在控制端口挂载 Runtime 路由。
- 模型恢复、地址探测和 socket／数据库绑定工作放在线程池，gateway 限流仍在同一个事件循环中。
- 清理凭证失败不输出引用名、异常内容或堆栈，原始业务异常继续向上传播。

## 验证 checklist

- [x] 复现并修复个人 API 误拦、重复路由、同步启动 I/O、敏感异常日志。
- [x] provisioner 返回不可变网络描述，Hub 复用同一份快照。
- [x] 单测覆盖不同 bridge 子网、桌面地址、非法地址、部分绑定失败与端口复用。
- [x] Colima 实机：仅回环监听，容器可鉴权访问，宿主机非回环地址不可访问。
- [x] Linux 实机：通过 Docker API 获取 bridge 网关，只监听明确接口，容器可访问。
- [x] Hub 回归、静态检查与中英文文档检查全部通过。

2026-09-17 验证结果：QwenPaw conda 环境下，Hub、Runtime 边界与 CLI 回归共 194 通过、1 个平台用例跳过；pre-commit 的类型、格式与静态检查通过；website 类型与格式检查通过。Colima 使用动态查询到的内部 DNS 完成容器验证；未改动宿主机全局 DNS。原生 Linux 使用真实 Docker API 探测出当时的 bridge 网关 `172.18.0.1`，进程仅监听该接口与回环接口；其他宿主机接口无法连接。两个环境中，模型目录正确凭证返回 200、错误凭证返回 401，模型端口的管理 API 返回 404。测试使用临时数据与容器，不访问真实供应商。
