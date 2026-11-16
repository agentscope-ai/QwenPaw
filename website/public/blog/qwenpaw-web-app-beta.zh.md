---
title: "QwenPaw Web App Beta：从手机访问云端与本地工作区"
date: 2026-11-16
author: QwenPaw Team
tags: [Web App, PWA, Mobile, Beta]
excerpt: "在 Console 绑定 Platform，扫码登录手机，再添加到桌面。一个入口切换云端和已绑定的本地 QwenPaw。"
related:
  heading: "在手机上开始使用"
  description: "Beta 功能，可能不稳定。请先确认本地和 Platform 均支持此功能。"
  items:
    - label: "文档"
      name: "手机 Web App 使用指南"
      href: "/docs/mobile"
---

# QwenPaw Web App Beta：从手机访问云端与本地工作区

手机入口采用 Web App：打开网页、登录、添加到桌面，就能在一个工作区菜单里切换云端部署和已绑定的本地 QwenPaw。此功能以 **Beta** 提供，可能不稳定。

## 从 Console 开始

统一手机入口是 [platform.agentscope.io/m](https://platform.agentscope.io/m)，需要本地与 Platform 配套部署此 Beta。

![Console 的 Platform 账号入口](/images/mobile/console-account.jpg)

先打开本地 Console 左下角的工作区菜单，选择“登录云账号”，再点击右上角的手机图标。手机扫码后，核对两端的数字，在电脑上确认登录，然后按照手机页面提示添加到桌面。

这次扫码登录的是完整 Platform 账号，可以切换该账号下的所有云端和绑定目标。二维码只携带短期、一次性授权，长期账号凭据不会放进二维码或网址中。

Hub 用户会看到本地账号和云上账号两种身份，远程连接始终指向自己的个人 Runtime。非 Hub 用户直接登录 Platform，无需为此创建本地账号。一个云账号可按节点配额绑定多个本地账号或设备。

## 添加到桌面后能做什么

![手机端共享 Console 模型与思考控件（演示环境）](/images/mobile/model-thinking.jpg)

手机直接使用所选节点同版本的 Console，模型、思考强度和模式保留在聊天输入框的原有控件中，其他页面也沿用同一套界面。切换目标时，对话和审批随目标隔离；切后台再回来时读取已有状态，不自动重复发送消息。节点升级后刷新其配套 Console，无需为手机维护另一套 UI。

本地实例仍在自己的电脑上运行。手机通过 Platform 访问它，不需要手动填写局域网地址；电脑需要保持开机并连接网络。

## 三种系统，共用网页入口

iPhone / iPad 使用 Safari 的“分享 → 添加到主屏幕”。Android 在支持时可点击安装，也可以从浏览器菜单添加。HarmonyOS 使用系统浏览器提供的桌面入口；具体能力取决于版本，不承诺所有机型都能安装成独立应用。

这一路径通过浏览器分发，无需原生手机安装包。附件、文件工作台和终端沿用节点能力与权限，浏览器安装、语音和后台行为仍需按机型验证；暂不提供推送通知或离线执行。

完整步骤、账号授权范围和常见问题见 [手机 Web App 使用指南](/docs/mobile)。
