# 向量模型

假设一个月前，你和 QwenPaw 讨论过：“这次先不迁移数据库，发布后再评估。”今天你问：“当时为什么沿用了旧的数据方案？”

两句话意思相近，却几乎没有相同的关键词。只靠关键词搜索，很可能找不到那段记忆；Embedding 的作用，就是帮助 QwenPaw 识别这种“说法不同、意思相近”的内容。

它不是另一套记忆，也不会替你生成答案。它只是给现有记忆增加一种按语义查找的方式。

## 它怎样帮助长期记忆

QwenPaw 的记忆仍然保存在 workspace 的 Markdown 文件中。启用 Embedding 后，ReMeLight 会为 `memory/` 和 `digest/` 中的文本生成向量，并在搜索时同时使用两条路径：

- **BM25 关键词搜索**：擅长函数名、错误码、产品名和原句中的精确词；
- **Embedding 语义搜索**：擅长同义表达、自然语言改写和主题相关内容；
- **RRF 融合**：综合两路结果的排名，把更相关的记忆排在前面。

例如，搜索“用户平时怎样去上班”，关键词搜索未必能命中“我首选的通勤工具是一辆轻便自行车”，语义搜索则更容易把两者联系起来。反过来，搜索 `HTTP 409` 或具体函数名时，关键词搜索通常更可靠。

Embedding 是可选的。没有配置时，BM25 和 Wikilink 展开仍然正常工作；小型知识库或主要搜索精确术语的场景，不一定需要向量模型。

## 可以把向量理解成“语义坐标”

Embedding 模型会把一段文本转换成一组固定长度的数字，也就是向量。意思相近的文本会落在相近的位置，因此即使用词不同，也能通过距离找到彼此。

文档和查询必须由兼容的模型放进同一个“坐标系”。这带来两个重要结论：

1. `dimensions` 必须与模型实际输出的维度一致，它不是可以随意填写的目标值；
2. 更换后端、服务地址、模型、维度或维度控制方式后，必须重建记忆索引。

即使两个模型都输出 1024 维向量，也不代表它们使用同一套坐标系。旧模型生成的文档向量不能与新模型生成的查询向量混用。

记忆文件始终是事实来源，向量和索引只是可以重新生成的派生数据。重建索引不会改写你的 Markdown 记忆。

## 当前能力与边界

QwenPaw 通过 AgentScope 2.x 连接 `openai`、`dashscope`、`dashscope_multimodal`、`gemini` 和 `ollama` 后端。目前只有 ReMeLight 直接使用这里的配置。

需要注意：

- 当前只向模型发送 ReMeLight 产生的**文本**；选择多模态类型或模型，不会让 QwenPaw 自动读取图片、音频、视频或 PDF；
- Embedding 不会捕获或整理记忆，也没有独立的 Agent 工具；它只为 `memory_search` 和 digest 相似度查询补充语义信号；
- 选择 ADBPG 等其他记忆后端时，向量能力由对应服务管理，不读取这里的 ReMeLight 配置；
- 相同输入可以使用本地缓存，减少重复计算和 API 调用。

## 在控制台中配置

进入 **Agent 配置 → 运行配置 → 长期记忆 → 向量模型配置**：

1. 选择与服务接口匹配的 SDK 类型；
2. 填写模型名称、API Key 和服务地址；
3. 填写模型实际输出的向量维度；
4. 点击“测试 Embedding 服务”；
5. 测试成功后保存配置；如果控制台提示向量空间已变化，再执行“重建记忆索引”。

![长期记忆中的 Embedding 模型配置区域](https://img.alicdn.com/imgextra/i2/O1CN01Er7z0tejkhL6wWB4_!!6000000004853-0-tps-3420-1314.jpg)

配置过程中需要区分以下几个阶段：

- **已开启**：当前表单已经填齐启用所需字段，不代表服务可访问；
- **已验证**：当前表单参数完成过一次真实请求，返回维度与配置一致；
- **已保存**：配置已经写入运行配置；同一向量空间的变更可热更新，向量空间变化则会暂停向量搜索并等待重建；
- **需要重建索引**：模型的语义坐标系发生变化，旧向量需要重新生成。

![Embedding 服务已验证并显示实际维度与耗时](https://img.alicdn.com/imgextra/i1/O1CN01LQlWGm6qD4I1gTsS_!!6000000003153-0-tps-830-134.jpg)

测试会发送一条真实文本请求，并检查服务能否在 `health_check_timeout` 内返回非空、有限数值组成且维度正确的向量；该超时默认是 15 秒。它只能证明当前参数可以完成一次调用；首次启用或重建索引仍需处理全部现有记忆，也可能遇到配额、速率限制或超长输入。

## 验证语义搜索

可以用一组“意思相近、关键词不同”的句子验证向量分支：

1. 保存一条记忆：“我首选的通勤工具是一辆轻便自行车。”
2. 搜索：“用户平时怎样去上班？”
3. 检查原始结果中是否找回该记忆，并出现数值形式的 `vector=...`。

```text
请调用 memory_search 工具搜索“用户平时怎样去上班？”。请原样返回工具结果，
包括 score、vector、keyword 字段，不要总结或改写。
```

- `vector` 为数值，表示向量分支命中；`-` 表示未命中；
- `keyword` 为数值，表示 BM25 分支命中；`-` 表示未命中；
- `score` 通常是两路候选的 RRF 融合分数，只有一路工作时也可能是该分支的原始分数。

## 常见问题

### 维度不匹配

`dimensions` 默认用于严格校验。除非模型和接口明确支持可变维度，否则应填写模型的原生输出维度。配置期望 256 维而服务返回 1024 维时，测试会直接失败：

<img class="embedding-dialog" src="https://img.alicdn.com/imgextra/i4/O1CN01ZFtJXcpF1MH1GnlE_!!6000000004901-0-tps-626-242.jpg" alt="Embedding 测试因期望维度与实际维度不一致而失败" />

`use_dimensions` 只决定 `openai` 后端是否把维度参数发给服务，不会关闭返回值校验。某些 OpenAI 兼容服务不接受该参数，此时关闭它，并把 `dimensions` 填成服务实际返回的维度。

### 更换模型后搜索异常

保存新的后端、地址、模型、维度或 `use_dimensions` 后，按照控制台提示重建索引。重建成功前，向量搜索保持不可用，但 BM25 关键词搜索仍可使用。只更换 API Key 不会改变向量空间，不需要重建。

维护 API 可以通过 `scope=embedding` 只重建向量，或通过默认的 `scope=all` 依次重建 BM25 和向量：

```http
POST /api/agents/{agentId}/memory/reindex?scope=embedding
```

如果决定放弃尚未重建的向量空间变更，可以在控制台撤销，或调用以下接口恢复与现有向量匹配的上一份配置：

```http
POST /api/agents/{agentId}/memory/reindex/undo
```

<img class="embedding-dialog" src="https://img.alicdn.com/imgextra/i3/O1CN01BCTjXC0jfMG1GYA0_!!6000000005728-0-tps-624-276.jpg" alt="重建记忆索引前的确认提示" />

### 服务地址无法访问

- OpenAI 兼容服务请选择 `openai`，`base_url` 会作为 API 地址；
- DashScope 当前使用官方 SDK 目的地，自定义 `base_url` 不会改变请求地址；
- Gemini 当前不使用 `base_url`；
- Ollama 把 `base_url` 当作 `host`。QwenPaw 在容器中运行时，`localhost` 指向容器自身，应填写进程实际可达的地址。

### 长文本或批量请求失败

`max_input_length` 是单条输入的近似**字符**预算，不是精确 token 上限。遇到 context length、HTTP 400、请求体过大或速率限制时，先减小 `max_input_length` 或 `max_batch_size`。缓存越大占用的内存和磁盘也越多。

## 参数配置

配置位于 `agent.json` 的 `running.reme_light_memory_config.embedding_model_config`。

### 后端

| `backend`              | 凭证与地址                             | 备注                                                                  |
| ---------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| `openai`               | `api_key` 必填；`base_url` 可选        | 用于 OpenAI 及 OpenAI 兼容文本向量服务；仅此后端使用 `use_dimensions` |
| `dashscope`            | `api_key` 必填                         | 模型名决定文本或多模态 API 路径；QwenPaw 当前只发送文本               |
| `dashscope_multimodal` | `api_key` 必填                         | 与 `dashscope` 使用相同适配；不会自动读取多模态文件                   |
| `gemini`               | `api_key` 必填                         | 当前只发送文本，不开放 `task_type`，也不使用 `base_url`               |
| `ollama`               | 不需要 API Key；`base_url` 作为 `host` | 本地或自托管文本向量服务，QwenPaw 进程必须能访问该地址                |

### 字段

| 字段                   | 默认值     | 作用                                                    |
| ---------------------- | ---------- | ------------------------------------------------------- |
| `backend`              | `"openai"` | 调用服务所用的 SDK 类型                                 |
| `api_key`              | `""`       | 服务凭证；Ollama 不使用                                 |
| `base_url`             | `""`       | OpenAI API 地址或 Ollama Host                           |
| `model_name`           | `""`       | 模型名称；所有后端都必填                                |
| `dimensions`           | `1024`     | 模型实际输出维度，用于严格校验和索引兼容判断            |
| `use_dimensions`       | `false`    | 仅限 `openai`；是否在请求中发送维度参数                 |
| `enable_cache`         | `true`     | 是否缓存相同文本的向量结果                              |
| `max_cache_size`       | `10000`    | 本地缓存最大条目数                                      |
| `max_input_length`     | `8192`     | 单条输入的近似字符预算                                  |
| `max_batch_size`       | `10`       | ReMeLight 每批提交的最大条目数                          |
| `health_check_timeout` | `15.0`     | 连接测试和启动健康检查的单次超时秒数，范围为 `(0, 300]` |

OpenAI 兼容服务示例：

```json
{
  "running": {
    "reme_light_memory_config": {
      "embedding_model_config": {
        "backend": "openai",
        "api_key": "your-api-key",
        "base_url": "https://your-embedding-service.example.com/v1",
        "model_name": "your-embedding-model",
        "dimensions": 1024,
        "use_dimensions": false,
        "enable_cache": true,
        "max_cache_size": 10000,
        "max_input_length": 8192,
        "max_batch_size": 10,
        "health_check_timeout": 15.0
      }
    }
  }
}
```

QwenPaw 正常运行时最多重试 3 次；测试时只重试 1 次，并使用 `health_check_timeout` 作为超时。AgentScope 还会按厂商限制继续拆分批次，因此 `max_batch_size` 是上游限制，实际可用值仍取决于具体模型和服务。

## 相关页面

- [长期记忆](./memory) — 记忆文件、索引与搜索流程
- [智能体记忆进化与主动交互](./memory-evolving-and-proactive) — Auto Memory、Auto Dream、Auto Memory Search 与 Proactive 工作流
- [配置与工作目录](./config) — Agent 配置文件与工作区结构
