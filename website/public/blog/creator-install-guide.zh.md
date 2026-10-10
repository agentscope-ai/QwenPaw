---
title: "QwenPaw Creator：从安装到开始创作"
date: 2026-08-19
author: QwenPaw Team
tags: [QwenPaw Creator, 视频创作, 安装指南, Agentic Workflow]
cover: https://img.alicdn.com/imgextra/i3/O1CN01BrV3VrZ2axF5qXky_!!6000000006553-2-tps-2880-1620.png
excerpt: "了解 QwenPaw Creator 的核心能力，并通过 7 个步骤完成安装、模型配置与首次打开。"
---

# QwenPaw Creator：从安装到开始创作

> **QwenPaw Creator** 是一个 Agentic 视频创作平台：从一句想法生成短剧，或把现有素材剪成成片，Agent 团队全程协作，关键决定始终在你手中。
>
> 本文将带你了解 Creator 的核心能力，并通过 7 个步骤完成安装与首次打开。QwenPaw 本身的安装请参考官网：<https://qwenpaw.agentscope.io/>

![QwenPaw Creator 产品演示](https://cloud.video.taobao.com/vod/QrQ22smEYzVP5QtchnWO6ix6caO84v72wVKmqDmRoDY.mp4)

_QwenPaw Creator 产品演示：从创意输入到视频创作工作流。_

截图中红色方框与数字圆标为操作标注（① ② ③ ……），按步骤顺序排列。

---

## 什么是 QwenPaw Creator？

在 Creator 里，你负责提出目标、提供素材和把握方向，Agent 团队负责策划、生成、剪辑与合成，并在关键节点把决定权交还给你。

### 核心能力

- **Agent 贯穿全程**：编剧、导演、视觉开发、动效、剪辑等 Specialist 按项目状态协作，不是一次性生成后就结束；
- **两条创作路径**：从一句想法生成短剧（剧本 → 分镜 → 参考生视频 → 合成），或将一批现有素材剪成成片（VLM/ASR 理解素材 → 剪辑方案 → 人机精修 → 合成）；
- **选中即上下文**：时间线上的时间点、片段、字幕、动效、转场、资产甚至页面文本，都可以选中交给 Agent 精准修改，也可以直接手动精修；
- **你始终掌舵**：Agent 的每次改动进入决策托盘，可保留或撤销；调用付费生成模型前会先展示预估费用确认卡。

### 原生集成 Qwen-MM-Plugins

Creator 原生集成了 [Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins)——一套让任何 Agent 具备原生多模态能力的插件集，开箱即得以下能力：

- **core（基础视觉）**：图像 / 视频 / 文档 / 3D 模型的动态分辨率阅读，含 OCR、目标定位（grounding）、分割、语音识别（ASR）、视觉问答与联网搜索；
- **video-memory（长视频记忆）**：分层图记忆，支撑对超长视频素材的理解、检索与问答；
- **video-edit（视频编辑）**：剪辑工作流与图像 / 视频 / 音频生成，含黑场检测、响度检测、审阅门禁等质控能力，保障成片质量；
- **edu-agent（教学视频）**：把数理题目或图片转化为分步讲解视频 / 交互页面。

---

## 开始之前：先打开 QwenPaw

按官网指引安装好 QwenPaw 后（安装方式见官网 [快速开始](https://qwenpaw.agentscope.io/#qwenpaw-quickstart)，支持 pip / 一键脚本 / Docker / 云端 / 桌面端），在终端启动它，浏览器会自动打开控制台：

```bash
# 启动 QwenPaw（默认监听 127.0.0.1:8088）
qwenpaw app

# 若浏览器未自动打开，手动访问
open http://127.0.0.1:8088
```

> 本教程使用默认本地模式：首次启动无需注册账号，进入即用。

---

## 步骤 1：进入主界面

启动 QwenPaw 后，浏览器会自动打开控制台主界面（Chat 页面）。

![步骤 1：QwenPaw 主界面](https://img.alicdn.com/imgextra/i2/O1CN01fvYmw40BXLL5qXky_!!6000000007717-2-tps-2880-1620.png)

_红框标注①：左侧导航栏中的「应用」入口。_

---

## 步骤 2：打开「应用」中心

点击左侧导航栏中的 **应用**（红色圆标 ① 处），进入应用中心。

![步骤 2：点击左侧「应用」](https://img.alicdn.com/imgextra/i2/O1CN011STeolhCvZJ5qXky_!!6000000000214-2-tps-2880-1620.png)

_红框标注①：「应用」菜单项。首次进入时如果还没有安装任何应用，会看到空态引导页。_

---

## 步骤 3：选择 Creator 并点击「安装」

切换到 **官方应用** 页签，找到 **QwenPaw Creator** 卡片，点击卡片右下角的 **安装** 按钮（圆标 ① 处）。

![步骤 3：官方应用页签中的 Creator 卡片](https://img.alicdn.com/imgextra/i4/O1CN01MFQj17c3uGC5qXky_!!6000000001609-2-tps-2880-1620.png)

_红框标注①：Creator 卡片及其「安装」按钮。_

---

## 步骤 4：等待安装完成

点击安装后，按钮立即进入「正在安装…」状态，稍等片刻即可。

![步骤 4：正在安装 Creator](https://img.alicdn.com/imgextra/i4/O1CN01vMj1GXuwbeD5qXky_!!6000000000654-2-tps-2880-1620.png)

_红框标注①：「安装」按钮变为「正在安装…」加载态。_

---

## 步骤 5：确认安装成功

安装完成后，页面顶部会弹出绿色对勾提示 **「已安装: QwenPaw Creator」**。

![步骤 5：安装成功提示](https://img.alicdn.com/imgextra/i3/O1CN01khWNWYm8iTG5qXky_!!6000000004768-2-tps-2880-1620.png)

_红框标注①：安装成功的 Toast 提示。_

---

## 步骤 6：在「我的应用」中查看 Creator

返回 **我的应用** 页签，Creator 卡片已经出现，卡片上显示「已安装」标记。

![步骤 6：我的应用中的 Creator](https://img.alicdn.com/imgextra/i1/O1CN01L9fm1RpQJZJ5qXky_!!6000000004775-2-tps-2880-1620.png)

_红框标注①：Creator 应用卡片（含「已安装」绿色标记）。_

---

## 步骤 7：点击「打开」，开始使用 Creator

点击 Creator 卡片上的 **打开** 按钮（圆标 ① 处），即可进入 Creator 创作界面：输入你的创意想法，选择模型与画幅，即可开始创作。

![步骤 7：打开 Creator](https://img.alicdn.com/imgextra/i3/O1CN01BrV3VrZ2axF5qXky_!!6000000006553-2-tps-2880-1620.png)

_红框标注①：「打开」按钮；下方即打开后的 Creator 界面。_

> 首次使用 Creator 需要配置模型：点击首页右上角的设置入口，按引导完成模型配置后即可开始生成。
