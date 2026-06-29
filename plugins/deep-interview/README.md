# Deep Interview Loop Plugin

苏格拉底式提问循环 — 通过权重化 ambiguity 评分深挖需求模糊点。

## 使用方法

在 Chat 中输入 `/deep-interview <主题或需求描述>`。

## 特点

- 软判断（LLM-as-Judge）：由 LLM 评估 ambiguity 是否低于阈值
- 无状态：不需要 state file，纯对话驱动
- 轻量循环：最大 20 轮，token 预算 100k
