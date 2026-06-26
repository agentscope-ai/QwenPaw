# 错误恢复与回退

执行前自检、SQL 执行及字面量取值失败时按类型回退；**禁止**同一 SQL 盲目重试超过 2 次。

## 执行错误

| 错误类型 | 典型原因 | 回退 | 动作 |
|----------|----------|------|------|
| 权限 / PERMISSION_DENIED | 无读权限 | 元数据 / SQL | 重拉元数据；修正表名；**不要**换 project 重试 |
| 语法 / ODPS_SYNTAX | 函数/语法错误 | SQL | 对照 `dialect-rules.md` |
| TABLE_NOT_FOUND | 表名错误 | 元数据 | 核对 `table_name` |
| COLUMN_NOT_FOUND | 列不存在 | 元数据 / SQL | 重拉 schema 或改投影 |
| PARTITION_REQUIRED | 缺分区谓词 | SQL | 加 `ds`/`pt` |
| 扫描过大 / 超时 | SQL 过重 | SQL | 见 `performance.md` |
| CONNECTOR_NOT_CONFIGURED | 连接未配置 | — | 停止；提示配置连接 |
| EXEC_TIMEOUT | 超时 | SQL | 缩小时间窗、优化 SQL |
| ENGINE_ERROR | 其他 | SQL / 元数据 | 读 message；记录 remediation |

## 字面量取值错误

| 情况 | 回退 |
|------|------|
| `get_dimension_values` 为空或未命中 | DISTINCT 探针；仍无 → 换维度/换表或重拉元数据 |
| 探针无权限 | 换表或申请权限 |
| distinct 为空 | 换列/换表；勿臆造枚举 |
| 多值无法匹配 | 问用户确认 |

## 空结果（row_count=0）

不算 error，但 **不要假装成功**：

1. 检查 `scope` 时间/过滤；
2. 检查澄清口径与维度列；
3. 检查 SQL WHERE；
4. 仍为空 → 说明「口径下无数据」。

## 重试纪律

- 同一 SQL + 同一错误：**最多 1 次**自动修复；
- 第二次仍失败 → 向用户说明 blocker；
- **禁止**绕过标准执行通道。
