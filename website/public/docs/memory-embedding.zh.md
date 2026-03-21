# Embedding 配置详解

长期记忆的向量搜索功能需要配置 Embedding 服务。本文档详细说明配置方式和常见问题。

> 本文档是 [长期记忆](memory.zh.md) 的补充说明。

---

## 配置优先级

```
config.json (embedding_config) > 环境变量 > 默认值
```

**说明：**

- `api_key`、`base_url`、`model_name` 三个参数支持从环境变量回退
- 其他参数只能通过 `config.json` 配置

---

## config.json 配置

在 `config.json` 的 `running.embedding_config` 中配置：

```json
{
  "running": {
    "embedding_config": {
      "backend": "openai",
      "api_key": "your-api-key",
      "base_url": "https://api.openai.com/v1",
      "model_name": "text-embedding-3-small",
      "dimensions": 1536,
      "enable_cache": true,
      "use_dimensions": false,
      "max_cache_size": 2000,
      "max_input_length": 8192,
      "max_batch_size": 10
    }
  }
}
```

### 完整参数说明

| 参数               | 类型   | 必填 | 默认值     | 说明                                                 |
| ------------------ | ------ | ---- | ---------- | ---------------------------------------------------- |
| `backend`          | string | 否   | `"openai"` | 后端类型，目前支持 `openai`（OpenAI 兼容 API）       |
| `api_key`          | string | 是\* | `""`       | API 密钥，可通过环境变量 `EMBEDDING_API_KEY` 设置    |
| `base_url`         | string | 是\* | `""`       | API 地址，可通过环境变量 `EMBEDDING_BASE_URL` 设置   |
| `model_name`       | string | 是\* | `""`       | 模型名称，可通过环境变量 `EMBEDDING_MODEL_NAME` 设置 |
| `dimensions`       | int    | 否   | `1536`     | 向量维度（需与模型匹配）                             |
| `enable_cache`     | bool   | 否   | `true`     | 是否启用向量缓存                                     |
| `use_dimensions`   | bool   | 否   | `false`    | 是否在请求中发送 dimensions 参数                     |
| `max_cache_size`   | int    | 否   | `2000`     | 最大缓存条目数                                       |
| `max_input_length` | int    | 否   | `8192`     | 最大输入文本长度（字符数）                           |
| `max_batch_size`   | int    | 否   | `10`       | 批处理时每批最大数量                                 |

_\* 必须至少配置 `base_url` 和 `model_name` 才能启用向量搜索_

### `use_dimensions` 参数说明

某些模型托管服务（如 vLLM）不支持 OpenAI API 的 `dimensions` 参数。如果遇到错误：

```
Error: dimensions parameter is not supported by this model
```

请将 `use_dimensions` 设置为 `false`。

---

## 环境变量配置

适用于容器化部署或不想修改配置文件的场景：

```bash
# Linux/macOS
export EMBEDDING_API_KEY="your-api-key"
export EMBEDDING_BASE_URL="https://api.openai.com/v1"
export EMBEDDING_MODEL_NAME="text-embedding-3-small"
export FTS_ENABLED="true"
export MEMORY_STORE_BACKEND="auto"
```

```powershell
# Windows PowerShell
$env:EMBEDDING_API_KEY="your-api-key"
$env:EMBEDDING_BASE_URL="https://api.openai.com/v1"
$env:EMBEDDING_MODEL_NAME="text-embedding-3-small"
$env:FTS_ENABLED="true"
$env:MEMORY_STORE_BACKEND="auto"
```

### 环境变量说明

| 变量名                 | 默认值   | 说明                                |
| ---------------------- | -------- | ----------------------------------- |
| `EMBEDDING_API_KEY`    | `""`     | API 密钥（config.json 优先）        |
| `EMBEDDING_BASE_URL`   | `""`     | API 地址（config.json 优先）        |
| `EMBEDDING_MODEL_NAME` | `""`     | 模型名称（config.json 优先）        |
| `FTS_ENABLED`          | `"true"` | 是否启用全文搜索                    |
| `MEMORY_STORE_BACKEND` | `"auto"` | 存储后端：`auto`、`local`、`chroma` |

### 存储后端选择

| 值       | 行为                                        |
| -------- | ------------------------------------------- |
| `auto`   | Windows 使用 `local`，其他系统使用 `chroma` |
| `local`  | 使用本地文件存储，无需额外依赖              |
| `chroma` | 使用 ChromaDB 向量数据库，性能更好          |

---

## 配置示例

### OpenAI 官方

```json
{
  "running": {
    "embedding_config": {
      "backend": "openai",
      "api_key": "sk-xxxxxxxxxxxxxxxx",
      "base_url": "https://api.openai.com/v1",
      "model_name": "text-embedding-3-small",
      "dimensions": 1536,
      "enable_cache": true,
      "use_dimensions": true
    }
  }
}
```

### Azure OpenAI

```json
{
  "running": {
    "embedding_config": {
      "backend": "openai",
      "api_key": "your-azure-api-key",
      "base_url": "https://your-resource.openai.azure.com/openai/deployments/your-deployment",
      "model_name": "text-embedding-ada-002",
      "dimensions": 1536,
      "enable_cache": true,
      "use_dimensions": false
    }
  }
}
```

### 本地 Ollama（推荐）

```json
{
  "running": {
    "embedding_config": {
      "backend": "openai",
      "api_key": "ollama",
      "base_url": "http://127.0.0.1:11434/v1",
      "model_name": "bge-m3",
      "dimensions": 1024,
      "enable_cache": true,
      "use_dimensions": false
    }
  }
}
```

**推荐本地模型：**

| 模型               | 维度 | 大小   | 说明               |
| ------------------ | ---- | ------ | ------------------ |
| `bge-m3:latest`    | 1024 | 1.2 GB | 中英文效果好，推荐 |
| `bge-large:335m`   | 1024 | 670 MB | 轻量级             |
| `nomic-embed-text` | 768  | 274 MB | 小巧高效           |

**安装 Ollama 模型：**

```bash
# 拉取 Embedding 模型
ollama pull bge-m3

# 启动服务
ollama serve
```

### 其他 OpenAI 兼容服务

```json
{
  "running": {
    "embedding_config": {
      "backend": "openai",
      "api_key": "your-api-key",
      "base_url": "https://your-provider.com/v1",
      "model_name": "embedding-model-name",
      "dimensions": 1024,
      "enable_cache": true,
      "use_dimensions": false
    }
  }
}
```

---

## 验证配置

### 检查日志

启动 CoPaw 后，查看日志中的 Embedding 配置信息：

```
INFO: Embedding config: {'backend': 'openai', ...}, vector_enabled=True
```

如果 `vector_enabled=True`，说明向量搜索已启用。

### 测试记忆搜索

在对话中测试记忆搜索功能：

```
搜索关于 XXX 的记忆
```

如果向量搜索未启用，将使用全文搜索（FTS）作为后备。

---

## 常见问题

### 向量搜索没有启用？

检查以下条件：

1. `base_url` 和 `model_name` 必须配置
2. API 服务必须可用
3. 如果是本地服务（如 Ollama），确保服务已启动

### Windows 下应该用什么存储后端？

Windows 默认使用 `local` 后端，这是最佳选择。如需使用 ChromaDB，需要额外安装依赖并可能遇到兼容性问题。

### 配置后还是报错？

常见错误排查：

1. **SSL 证书错误**：Windows 下可能遇到，检查网络配置
2. **连接超时**：检查 `base_url` 是否正确，服务是否可达
3. **维度不匹配**：确保 `dimensions` 与模型实际输出一致

---

## 相关链接

- [长期记忆](memory.zh.md)
- [故障排查](troubleshooting.zh.md)
- [Ollama 官网](https://ollama.com)
