# Airport SMS 运行手册

## 备份

每日导出 SQLite `cases` 与 `sessions` 表。保留至少 30 天。

## 密钥轮换

1. 在密钥库生成新 API key。
2. 双写窗口内新旧 key 均可验证。
3. 切流量到新 key 后废止旧 key。
4. 记录轮换时间与操作者。

## 审批 SLA

`submit_case` / `close_case` / `escalate` / `notify_ops` 的 ASK 默认可等待 15 分钟。超时按 deny，案件状态不变。

## 手册条款更新

更新 `assets/manuals/` 后重建 memory 索引。未重建前检索可能返回旧条款。

## 外部 SMS DB 桥

`external_sms_bridge.enabled` 默认 `false`。未完成幂等方案前不要打开。

## 健康检查

`GET /health` 应返回 `{"status":"ok"}`。通道子进程挂掉时宿主仍应健康。
