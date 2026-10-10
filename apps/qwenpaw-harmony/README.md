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

- `entry/src/main/ets/pages/` — Index（壳：HdsNavigation + 4 tab）/ ChatDetail（会话详情）
- `entry/src/main/ets/components/` — ConnectPanel / AgentsTab / CommunityTab / WorkbenchTab / ApprovalCard
- `entry/src/main/ets/services/` — RelayClient / RelayCodec / AgentStore / ThemeManager / SseParser / ChatDetailService
- 上游参考：QwenPaw PR #7378 `apps/qwenpaw-mobile`（React Native）
