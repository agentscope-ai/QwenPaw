# 故障排查

CoPaw 使用过程中可能遇到的常见问题及解决方案。

---

## 端口冲突

CoPaw 默认使用端口 **8088** 提供 Web UI 和 API 服务。如果端口被占用，会导致启动失败：

```
OSError: [WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。
```

或

```
OSError: [Errno 98] Address already in use
```

### 常见占用端口的应用

| 应用          | 说明                           |
| ------------- | ------------------------------ |
| Jenkins       | CI/CD 服务，默认端口 8080/8088 |
| Apache Tomcat | Java 应用服务器                |
| 其他 Web 服务 | 本地开发的服务                 |
| 代理软件      | 如 Fiddler、Charles 等         |

### 解决方案一：修改 CoPaw 端口（推荐）

```powershell
# 使用 8089 端口启动
copaw app --port 8089

# 指定 host 和 port
copaw app --host 127.0.0.1 --port 8089
```

CoPaw 会记住上次使用的端口，下次启动无需再次指定。

### 解决方案二：查找并关闭占用进程

```powershell
# 查找占用端口的进程
netstat -ano | findstr :8088

# 输出示例：
# TCP    0.0.0.0:8088    0.0.0.0:0    LISTENING    12345
#                                               ^^^^^ 这是 PID

# 确认进程名称
tasklist /FI "PID eq 12345"

# 终止进程（谨慎操作）
taskkill /PID 12345 /F
```

### 解决方案三：配置防火墙

如果端口被 Windows 阻止，需要添加防火墙规则：

```powershell
# 以管理员身份运行
New-NetFirewallRule -DisplayName "CoPaw" -Direction Inbound -LocalPort 8088 -Protocol TCP -Action Allow
```

### 端口配置优先级

```
命令行参数 --port > last_api.json > 默认值 8088
```

---

## Embedding 配置问题

长期记忆的向量搜索功能需要配置 Embedding 服务。常见问题：

### 问题：未配置 Embedding 服务

**症状：** 启动时报错 `Embedding service not configured`

**解决方案：** 在 `config.json` 中配置 `embedding_config`：

```json
{
  "running": {
    "embedding_config": {
      "backend": "openai",
      "api_key": "your-api-key",
      "base_url": "https://api.openai.com/v1",
      "model_name": "text-embedding-3-small"
    }
  }
}
```

### 问题：Ollama Embedding 连接失败

**症状：** `Connection refused` 或 `Embedding failed`

**解决方案：**

1. 确认 Ollama 服务正在运行：

```powershell
curl http://127.0.0.1:11434/api/tags
```

2. 确认 Embedding 模型已安装：

```powershell
ollama list | findstr bge
```

3. 正确配置 `base_url`：

```json
{
  "running": {
    "embedding_config": {
      "backend": "openai",
      "api_key": "ollama",
      "base_url": "http://127.0.0.1:11434/v1",
      "model_name": "bge-m3"
    }
  }
}
```

### 问题：向量维度不匹配

**症状：** `Dimension mismatch` 错误

**解决方案：** 确保配置的 `dimensions` 与模型输出维度一致：

| 模型                   | 维度 |
| ---------------------- | ---- |
| text-embedding-3-small | 1536 |
| text-embedding-3-large | 3072 |
| bge-m3                 | 1024 |
| bge-large              | 1024 |

---

## Windows 编码问题

### 问题：控制台输出乱码

**症状：** 中文显示为乱码或问号

**解决方案：**

```powershell
# 切换控制台编码为 UTF-8
chcp 65001
```

或在 Python 脚本开头添加：

```python
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

### 问题：Emoji 输出报错

**症状：** `'gbk' codec can't encode character` 错误

**解决方案：** 过滤或替换 emoji 字符：

```python
def safe_print(text):
    """安全打印，处理 emoji 编码问题"""
    print(text.encode('gbk', errors='replace').decode('gbk'))
```

---

## 内存问题

### 问题：内存占用过高

**症状：** CoPaw 进程占用大量内存

**解决方案：**

1. 减少缓存大小：

```json
{
  "running": {
    "embedding_config": {
      "enable_cache": true,
      "max_cache_size": 500
    }
  }
}
```

2. 定期重启服务

3. 限制对话历史长度

---

## 日志查看

### 查看实时日志

```powershell
# 查看最新日志
Get-Content .copaw\logs\copaw.log -Tail 50 -Wait
```

### 日志文件位置

| 文件                    | 说明     |
| ----------------------- | -------- |
| `.copaw/logs/copaw.log` | 主日志   |
| `.copaw/logs/error.log` | 错误日志 |

---

## 相关链接

- [CoPaw 官方文档](https://copaw.agentscope.io/docs)
- [CoPaw GitHub Issues](https://github.com/agentscope-ai/CoPaw/issues)
- [CoPaw GitHub Discussions](https://github.com/agentscope-ai/CoPaw/discussions)
