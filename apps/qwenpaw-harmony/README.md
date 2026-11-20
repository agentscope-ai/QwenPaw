# QwenPaw 鸿蒙版（HarmonyOS NEXT）

bundleName：`io.agentscope.qwenpaw.mobile`（对齐上游 PR #7378 app.json）。
本工程为 React Native 版（`apps/qwenpaw-mobile`）的 HarmonyOS NEXT 原生移植，
工程实体在本目录（纯 ASCII 路径）。

## 构建（已验证 BUILD SUCCESSFUL）

```bash
cd <本目录> && env PATH=<工具链>/node24/bin:/usr/bin:/bin \
  JAVA_HOME=<工具链>/jdk21/<jdk-21> \
  DEVECO_SDK_HOME=<工具链>/command-line-tools/sdk \
  <工具链>/command-line-tools/tool/node/bin/node \
  <工具链>/command-line-tools/hvigor/bin/hvigorw.js assembleHap \
  --mode module -p 'module=entry@default' -p 'product=default' -p 'buildMode=debug' \
  --analyze=normal --parallel --incremental --no-daemon 2>&1 | tail -6
```

产物：`entry/build/default/outputs/default/entry-default-signed.hap`

## 平台/环境约束与踩坑记录

1. **路径（hvigor 00306003）**：工程路径仅允许 字母/数字/`-_.()空格@`，
   中文真实路径 0 task 即拦 → 工程放 ASCII 目录。
2. **inotify ENOSPC**：hvigor 的文件监视在 Linux 走 inotify，监视的
   require 树 watch 数超过 per-user 配额（`user.max_inotify_watches`）时报
   ENOSPC。用 `--no-daemon` 单次构建可规避；或提升配额
   `sudo sysctl -w user.max_inotify_watches=524288`（不执行不影响构建）。
3. 换工程路径后若 loader/缓存报旧绝对路径错误，清 `.hvigor/` 与 `entry/build/`
   重编。

## 本机文件（均不入库）

| 文件 | 用途 | 说明 |
|---|---|---|
| `build-profile.json5` | 签名配置与 SDK 档位 | 从 `build-profile.example.json5` 复制后填本机证书路径；仓库只保留模板 |
| `agconnect-services.json` | AppGallery Connect 配置 | 含 `client_secret` / `api_key`，**禁止提交**；从 AGC 下载后放工程根 |
| `.ohos/`、`build/`、`.hvigor/` | 本机构建缓存 | 已忽略 |

## 打包与上架

- **调试包**（`assembleHap --mode module`）用自动签名证书，只能装机调试，不能上传 AGC。
- **上架 / 邀请测试（AppTest）必须用发布证书 + 发布 profile 打包**（官方口径：邀请测试使用发布证书；
  调试证书生成的包仅支持本地调试）。流程：AGC 创建应用 → 申请发布证书与 profile →
  在 `build-profile.json5` 增加 release `signingConfigs` → `assembleHap -p buildMode=release`。
- 版本号在 `AppScope/app.json5`（`versionCode` / `versionName`），每次上传必须递增 `versionCode`。
- `compatibleSdkVersion` 目前与 target 同为 `26.0.0`，即只覆盖 HarmonyOS 6 及以上；要覆盖 5.x 需降档并回归。
- 接 Push Kit（系统远程通知）是独立能力，不影响上架：客户端用内置 `@kit.PushKit` 取 token 上报服务端，
  需手动签名、AGC 开通推送并申请通知自分类权益；未申请时默认按资讯营销类做频控（每设备每日 2/5 条）。
  首页 skill（`entity.system.home` + `action.system.home`）**不要配 uris**，否则推送会失败。

## 装机 / 冒烟

```bash
HDC=<CLT>/sdk/default/openharmony/toolchains/hdc
$HDC install -r entry/build/default/outputs/default/entry-default-signed.hap
$HDC shell aa force-stop io.agentscope.qwenpaw.mobile
$HDC shell aa start -b io.agentscope.qwenpaw.mobile -a EntryAbility
$HDC shell snapshot_display -f /data/local/tmp/x.jpeg && $HDC file recv /data/local/tmp/x.jpeg /tmp/x.jpeg
```

设备：鸿蒙真机（1316×2832，density≈3.6）

## 鸿蒙文档

ArkTS / ArkUI / HDS 组件 API 以 DevEco Studio 随附文档库与华为开发者官网
（developer.huawei.com）为准；UI 与交互逐项对照上游 `apps/qwenpaw-mobile`
（React Native）源码移植。

## 源码结构

- `entry/src/main/ets/pages/` — `Index`（壳：HdsNavigation + 4 tab）、`ChatDetailPage`（会话详情），
  以及设置 / 分类 / 模块 / 扫码 / 社区文章 / 平台部署等二级页
- `entry/src/main/ets/components/` — 各 tab 与聊天行渲染（ConnectPanel / AgentsTab / CommunityTab /
  WorkbenchTab / ChatRows / ChatPlaceholder …）
- `entry/src/main/ets/services/` — 数据与平台能力（Connection* / Chats* / AgentsService / ChatDetailService /
  SseParser / LivenessService / Theme* / MediaActions / Platform* …）
- `entry/src/main/ets/theme/` — 颜色 token、尺寸 token、按压反馈
- 上游参考：QwenPaw PR #7378 `apps/qwenpaw-mobile`（React Native）
