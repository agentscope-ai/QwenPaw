# DataPaw 数据源管理 API

数据源配置的 REST 接口，挂载在 host 的 `/api/datapaw/data-sources` 下。Schema 源码见 [`plugins/bundle/datapaw/core/routers/data_sources.py`](../plugins/bundle/datapaw/core/routers/data_sources.py)。

## 概述

| 项 | 说明 |
|---|---|
| Base URL | `/api/datapaw/data-sources` |
| 持久化 | `~/.qwenpaw/workspaces/datapaw/data_sources.json` |
| 认证 | 与 QwenPaw host 一致（浏览器 session / cookie） |
| 支持类型 | `mysql`、`postgresql`、`odps` |

## 数据模型

### DataSourceRecord

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 唯一标识，创建时自动生成 |
| `type` | string | `mysql` / `postgresql` / `odps` |
| `name` | string | 用户自定义名称，用于列表展示与对话页选择 |
| `config` | object | 类型相关连接参数（见下表） |
| `createdAt` | string | ISO8601 创建时间 |
| `updatedAt` | string | ISO8601 最后更新时间 |

### config 必填字段

**MySQL / PostgreSQL**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `host` | string | 是 | 数据库主机地址 |
| `port` | number | 是 | 端口（1–65535） |
| `user` | string | 是 | 用户名 |
| `password` | string | 是 | 密码（响应中 mask） |
| `db` | string | 是 | 数据库名 |

**ODPS**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `endpoint` | string | 是 | ODPS 服务 endpoint |
| `project_name` | string | 是 | 项目名称 |
| `access_id` | string | 是 | AccessKey ID |
| `access_key` | string | 是 | AccessKey Secret（响应中 mask） |
| `app_name` | string | 是 | 应用名称 |

### 敏感字段 mask 规则

`password`、`access_key` 在 API 响应中会 mask（显示前缀 + 星号 + 后缀，短于 8 字符则全部 mask）。

更新数据源时，若传入的 `password` / `access_key` 与 mask 后的值一致，则保留磁盘上的原值不变。

## 端点一览

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/` | 列表 |
| `GET` | `/types` | 支持的数据源类型 |
| `GET` | `/{id}` | 单条详情 |
| `POST` | `/` | 创建 |
| `PUT` | `/{id}` | 更新 |
| `DELETE` | `/{id}` | 删除 |
| `POST` | `/test` | 测试连接（不持久化） |

---

## GET / — 列表

返回所有已配置数据源，敏感字段已 mask。

### Example

**curl**

```bash
curl http://localhost:8080/api/datapaw/data-sources
```

**输入**

无请求体。

**输出 — 200**

```json
{
  "items": [
    {
      "id": "mysql-a1b2c3d4e5f6",
      "type": "mysql",
      "name": "用户库",
      "config": {
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "se********345",
        "db": "user_db"
      },
      "createdAt": "2026-06-11T03:00:00+00:00",
      "updatedAt": "2026-06-11T03:00:00+00:00"
    },
    {
      "id": "odps-f6e5d4c3b2a1",
      "type": "odps",
      "name": "数仓",
      "config": {
        "endpoint": "https://service.odps.aliyun.com/api",
        "project_name": "my_project",
        "access_id": "LT********5678",
        "access_key": "ab********xyz",
        "app_name": "datapaw"
      },
      "createdAt": "2026-06-11T04:00:00+00:00",
      "updatedAt": "2026-06-11T04:00:00+00:00"
    }
  ]
}
```

---

## GET /types — 支持的数据源类型

返回新增数据源表单可选的类型列表；MySQL / PostgreSQL 会附带默认端口。

### Example

**curl**

```bash
curl http://localhost:8080/api/datapaw/data-sources/types
```

**输入**

无请求体。

**输出 — 200**

```json
{
  "items": [
    { "type": "mysql", "defaultPort": 3306 },
    { "type": "postgresql", "defaultPort": 5432 },
    { "type": "odps" }
  ]
}
```

---

## GET /{id} — 单条详情

按 id 查询一条数据源，敏感字段已 mask。

### Example

**curl**

```bash
curl http://localhost:8080/api/datapaw/data-sources/mysql-a1b2c3d4e5f6
```

**输入**

路径参数 `id` = `mysql-a1b2c3d4e5f6`，无请求体。

**输出 — 200**

```json
{
  "id": "mysql-a1b2c3d4e5f6",
  "type": "mysql",
  "name": "用户库",
  "config": {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "se********345",
    "db": "user_db"
  },
  "createdAt": "2026-06-11T03:00:00+00:00",
  "updatedAt": "2026-06-11T03:00:00+00:00"
}
```

**输出 — 404**

```json
{
  "detail": "notFound"
}
```

---

## POST / — 创建

创建并持久化一条数据源。`name` 在同一 workspace 内不可重复。

### Example

**curl**

```bash
curl -X POST http://localhost:8080/api/datapaw/data-sources \
  -H "Content-Type: application/json" \
  -d '{
    "type": "mysql",
    "name": "用户库",
    "config": {
      "host": "127.0.0.1",
      "port": 3306,
      "user": "root",
      "password": "secret",
      "db": "user_db"
    }
  }'
```

**输入**

```json
{
  "type": "mysql",
  "name": "用户库",
  "config": {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "secret",
    "db": "user_db"
  }
}
```

**输出 — 200**

```json
{
  "id": "mysql-a1b2c3d4e5f6",
  "type": "mysql",
  "name": "用户库",
  "config": {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "se********345",
    "db": "user_db"
  },
  "createdAt": "2026-06-11T03:00:00+00:00",
  "updatedAt": "2026-06-11T03:00:00+00:00"
}
```

**输出 — 400**（缺少必填字段）

```json
{
  "detail": "hostRequired"
}
```

**输出 — 409**（名称重复）

```json
{
  "detail": "nameConflict"
}
```

---

## PUT /{id} — 更新

更新名称和/或 config。字段均可选，至少传一项。未修改的 config 字段可省略；`password` / `access_key` 传 mask 占位符时保留原值。

### Example

**curl**

```bash
curl -X PUT http://localhost:8080/api/datapaw/data-sources/mysql-a1b2c3d4e5f6 \
  -H "Content-Type: application/json" \
  -d '{
    "name": "用户库-生产",
    "config": {
      "host": "10.0.0.1",
      "password": "se********345"
    }
  }'
```

**输入**

路径参数 `id` = `mysql-a1b2c3d4e5f6`。

```json
{
  "name": "用户库-生产",
  "config": {
    "host": "10.0.0.1",
    "password": "se********345"
  }
}
```

**输出 — 200**

```json
{
  "id": "mysql-a1b2c3d4e5f6",
  "type": "mysql",
  "name": "用户库-生产",
  "config": {
    "host": "10.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "se********345",
    "db": "user_db"
  },
  "createdAt": "2026-06-11T03:00:00+00:00",
  "updatedAt": "2026-06-11T05:30:00+00:00"
}
```

**输出 — 404**

```json
{
  "detail": "notFound"
}
```

**输出 — 409**（新名称与其他数据源冲突）

```json
{
  "detail": "nameConflict"
}
```

---

## DELETE /{id} — 删除

按 id 删除一条数据源。

### Example

**curl**

```bash
curl -X DELETE http://localhost:8080/api/datapaw/data-sources/mysql-a1b2c3d4e5f6
```

**输入**

路径参数 `id` = `mysql-a1b2c3d4e5f6`，无请求体。

**输出 — 204**

无响应 body。

**输出 — 404**

```json
{
  "detail": "notFound"
}
```

---

## POST /test — 测试连接

探测连通性，**不写入**持久化文件。HTTP 始终返回 200，通过响应体中的 `success` 区分成败。

### Example（MySQL）

**curl**

```bash
curl -X POST http://localhost:8080/api/datapaw/data-sources/test \
  -H "Content-Type: application/json" \
  -d '{
    "type": "mysql",
    "config": {
      "host": "127.0.0.1",
      "port": 3306,
      "user": "root",
      "password": "secret",
      "db": "user_db"
    }
  }'
```

**输入**

```json
{
  "type": "mysql",
  "config": {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "secret",
    "db": "user_db"
  }
}
```

**输出 — 200（连接成功）**

```json
{
  "success": true,
  "message": "connectionOk",
  "latencyMs": 128
}
```

**输出 — 200（连接失败）**

```json
{
  "success": false,
  "message": "Access denied for user 'root'@'127.0.0.1' (using password: YES)",
  "latencyMs": 45
}
```

**输出 — 400**（缺少必填字段）

```json
{
  "detail": "passwordRequired"
}
```

---

## 依赖

连接测试需要以下 Python 包（见插件 `requirements.txt`）：

- `pymysql` — MySQL
- `psycopg2-binary` — PostgreSQL
- `pyodps` — ODPS

驱动未安装时，`POST /test` 返回 `{ "success": false, "message": "... is not installed on the server." }`。





[pg/hologres]
-- 阿里内网tongyi_busi
域名=tongyi-busi-cn-internal.hologres.aliyuncs.com
端口=8099
用户名=BASIC$datapaw_agent_user
密码=BASIC$damo_data_agent
数据库=tongyi_busi

-- 公网
域名=hgpostcn-cn-0w74oi088001-cn-hangzhou.hologres.aliyuncs.com
端口=80
用户名=BASIC$datapaw_agent_user
密码=BASIC$datapaw_agent_user
数据库=tongyi_datascope

[odps]
-- 阿里内网 无ak方案
app_name = "semantic-layer"
project = "damo_cdm"
endpoint = "http://service-corp.odps.aliyun-inc.com/api"

[mysql]
-- 公网
host = rm-bp16l6m2d1z3g2a8f1o.mysql.rds.aliyuncs.com
port = 3306
user = iic_data
password = Cat$12345678
dbname=bird_california_schools