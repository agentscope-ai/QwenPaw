# PR #7833 修复方案与 checklist

用户已授权直接修改、commit 并 push 当前分支。最终确认：共享管理员维护的 QwenPaw 安装；每用户一个常驻 runtime、一层 OS 沙箱、独立目录与持久化环境变量。不要求 Agent 间独立 OS 隔离。

详细边界见 [设计文档](hub-local-python-pawapp-auth-review.zh.md)，复现记录见 [补充审查](pr-7833-local-cli-review.zh.md)。

- [x] 撤回完整 Python 隔离、复制与每用户 venv；删除相关可写挂载，不增加旧格式兼容层。
- [x] 共享解释器与 scripts 路径，框架启动防止 cwd 模块遮蔽。
- [x] Local 子进程继承外层沙箱，不重复初始化或探测嵌套沙箱。
- [x] 独立环境持久化、控制项校验，managed 模式禁用 dotenv 与共享配置迁移。
- [x] managed env CLI 使用 runtime API，即时更新服务环境；失败不离线回退。
- [x] 插件 CLI 使用 runtime API，Local 缺依赖提示管理员安装，Docker 保留自动安装。
- [x] PawApp 桌面 gate、合法 ID、Cookie 范围及实际路由归属校验。
- [x] 后端/前端回归、真实 macOS 工具 shell → CLI → runtime 和重启持久化测试。
- [x] 最终格式检查（mypy、Black、flake8、pylint、Prettier）及类型检查。

提交与推送执行结果以 Git 提交记录和远端分支为准。


## 测试精简（2026-09-18）

- [x] 删除手写 Python -P 调用及内部沙箱类型断言，保留真实工具 shell → CLI → runtime 回归。
- [x] 删除重复的存储重载/子进程环境继承用例，保留真实 runtime 重启持久化 E2E。
- [x] 合并 PawApp 路由碰撞测试的重复搭建，保留核心 API、其他应用、写操作和碰撞拒绝断言。
- [x] 精简 CLI、manifest ID 和依赖安装参数组合；保留关键错误路径。
- [x] 受影响后端 37 项、前端 4 项通过；格式检查通过。
