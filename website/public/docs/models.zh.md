# 模型

在使用 QwenPaw 之前，您需要配置至少一个可用模型，QwenPaw 支持多种模型提供商，您可以在页面左侧边栏的 **设置 -> 模型** 页面进行配置和管理。

![全局默认模型与云端提供商](https://img.alicdn.com/imgextra/i2/O1CN010iWs8ko7wXC3FPfU_!!6000000002852-2-tps-1600-1000.png)

QwenPaw 支持多种 LLM 提供商：

- **本地提供商**（llama.cpp / Ollama / LM Studio）
- **云提供商**（一般需要 API Key）
- **自定义提供商**（如果预设的本地和云提供商无法满足您的需求）

QwenPaw 当前支持的本地供应商包括：

- [QwenPaw Local (llama.cpp)](https://github.com/ggml-org/llama.cpp)
- [Ollama](https://ollama.com/)
- [LM Studio](https://lmstudio.ai/)

QwenPaw Local 由可选插件提供。Ollama 和 LM Studio 需要单独安装。

QwenPaw 官方还提供了适合本地部署的 QwenPaw-Flash 系列模型，包含 2B、4B 和 9B 三个版本；除原始模型外，还提供 4 bit 和 8 bit 量化版本，适合不同的显存环境和性能需求。这些模型已经在 [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) 和 [Hugging Face](https://huggingface.co/agentscope-ai/models) 上开源，下面分别介绍如何在三种本地供应商中使用 QwenPaw-Flash。

## QwenPaw Local (llama.cpp) 配置

> QwenPaw Local 目前仍处于测试阶段，稳定性以及对 GPU 的兼容性存在问题，如果追求稳定或是需要使用 GPU 加速，短期内建议使用 Ollama 或 LM Studio 作为本地模型提供商。

全新安装时，**设置 → 模型 → 本地 & 自定义** 中有 Ollama 和 LM Studio，它们连接的是你单独运行的服务。如果希望由 QwenPaw 管理 llama.cpp 和 GGUF 文件，请按以下步骤操作：

![安装 QwenPaw Local 之前的本地提供商列表](https://img.alicdn.com/imgextra/i4/O1CN01knTfR9R1sgL3FPfU_!!6000000004916-2-tps-1600-1000.png)

1. 打开 **设置 → 扩展 → 插件 → 官方插件**，安装 **QwenPaw Local**（`local-llamacpp`）。如果已经安装，在 **已安装插件** 中确认已启用。
2. 回到 **模型 → 本地 & 自定义**，打开 **QwenPaw Local** 卡片的模型管理窗口。若缺少推理引擎，点击 **安装 llama.cpp**。安装插件本身不会下载引擎或模型。
3. 下载推荐模型，或选择 ModelScope、Hugging Face 并填写 GGUF 仓库 ID。如果已有权重，可以[手动导入 GGUF](./models#本地模型)，不必重复下载。
4. 点击已下载模型旁的 **启动**。Flash 会成为默认对话模型，Piccolo 会成为默认决策模型。两者共用一个服务，切换前请等待当前请求完成。**停止** 只关闭服务，不删除权重。

重启 QwenPaw 时，如果启用的智能体仍选用已启动过的本地模型，QwenPaw 会尝试恢复该模型。只使用云模型时，llama.cpp 不会随 App 启动。

### 使用本地 Piccolo 决策模型

在 QwenPaw Local 的 **决策模型** 列表中，按机器内存选择推荐的 BF16 或 Q8_0 版本，下载后点击 **启动**。如需 Q4_K_M，可在自定义下载中填写 GGUF 仓库 ID，例如 Hugging Face 的 `agentscope-ai/Piccolo-4B-Q4_K_M` 或 ModelScope 的 `AgentScope/Piccolo-4B-Q4_K_M`。

在 **模型 → 默认模型 → 决策模型** 确认已选中 Piccolo，再按用途配置智能体：

- **工具审查**：在智能体的安全设置中选择 **决策模型模式**，并在对话中开启工具审查。
- **上下文压缩**：在智能体的上下文设置中开启自动上下文压缩，再打开 **启用决策模型压缩**。

## Ollama 配置

在使用 Ollama 之前，您需要先在机器上安装最新版 [Ollama](https://ollama.com/download)，至少下载一个模型，并且在设置页面中将 Context Length 设置为至少 32k。

![Ollama 设置](https://img.alicdn.com/imgextra/i4/O1CN01qO1GW7AMDYH3FPfU_!!6000000006595-2-tps-1600-1000.png)

为了验证 Ollama 是否能够正常使用，可以进入 QwenPaw Ollama 提供商的 **设置** 页面，点击 **测试连接** 按钮来验证 QwenPaw 是否能够连接到 Ollama 服务。

> 对于将 QwenPaw 部署在 Docker 容器中的用户，如果 Ollama 安装在宿主机上，请确保 Docker 的网络配置允许容器访问宿主机的 Ollama 服务（在 `docker run` 命令中添加 `--add-host=host.docker.internal:host-gateway`），并将 API 地址设置为 `http://host.docker.internal:11434` 来实现连接。

如果您希望在 Ollama 中使用 QwenPaw-Flash，建议选择 `Q8_0` 或 `Q4_K_M` 量化版本，并按以下步骤导入：

1. 从 [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) 或 [Hugging Face](https://huggingface.co/agentscope-ai/models) 下载合适的 QwenPaw-Flash 量化模型，例如 `AgentScope/QwenPaw-Flash-4B-Q4_K_M`。

ModelScope CLI：

```bash
modelscope download --model AgentScope/QwenPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

Hugging Face CLI：

```bash
hf download agentscope-ai/QwenPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

2. 创建一个文本文件 `qwenpaw-flash.txt`，并将 `/path/to/your/qwenpaw-xxx.gguf` 替换为下载后的 `.gguf` 文件绝对路径：

```text
FROM /path/to/your/qwenpaw-xxx.gguf
TEMPLATE {{ .Prompt }}
RENDERER qwen3.5
PARSER qwen3.5
PARAMETER presence_penalty 1.5
PARAMETER temperature 1
PARAMETER top_k 20
PARAMETER top_p 0.95
```

3. 在终端中运行以下命令，将模型导入 Ollama：

```bash
ollama create qwenpaw-flash -f qwenpaw-flash.txt
```

4. 打开 Ollama 卡片的模型列表，点击刷新图标 **更新模型列表**，再启用要使用的模型。同步目录不会把模型权重下载到 QwenPaw。

## LM Studio 配置

在使用 LM Studio 之前，您需要先在机器上安装最新版 [LM Studio](https://lmstudio.ai/download)。

LM Studio 默认不会开启模型 API 服务，因此在 LM Studio 安装完成并下载模型后，您需要进入 **Developer -> Local Server** 页面，启动本地模型服务，并记录下 API 地址，默认为 `http://localhost:1234`。

![LM Studio 本地服务](https://gw.alicdn.com/imgextra/i3/O1CN01kLXu3D1VwRF3lokZz_!!6000000002717-2-tps-1654-1256.png)

为了保证 QwenPaw 中的使用体验，需要在 LM Studio 的 **Settings -> Model Defaults** 页面中将 **Default Context Length** 设置为至少 32768，并在 **Settings -> Developer** 页面中将 **Experimental Settings** 中的 "When applicable, separate `reasoning_content` and `content` in API responses" 选项打开。

![LM Studio 上下文长度](https://gw.alicdn.com/imgextra/i4/O1CN011jc2q71hc51etcf7x_!!6000000004297-2-tps-1654-1256.png)

![LM Studio 思考内容解析](https://gw.alicdn.com/imgextra/i4/O1CN01dInPGl1oDX6nOH0Wh_!!6000000005191-2-tps-1654-1256.png)

上述 LM Studio 配置完成后，可以进入 QwenPaw LM Studio 提供商的 **设置** 页面，输入 LM Studio 的 API 地址，该地址可以从 LM Studio 的 **Developer -> Local Server** 页面获取，但注意要后缀 `/v1`，例如 `http://localhost:1234/v1`。

如果您希望在 LM Studio 中使用 QwenPaw-Flash，建议同样选择 `Q8_0` 或 `Q4_K_M` 量化版本，并按以下步骤导入：

1. 从 [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) 或 [Hugging Face](https://huggingface.co/agentscope-ai/models) 下载合适的 QwenPaw-Flash 量化模型，例如 `AgentScope/QwenPaw-Flash-4B-Q4_K_M`。

ModelScope CLI：

```bash
modelscope download --model AgentScope/QwenPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

Hugging Face CLI：

```bash
hf download agentscope-ai/QwenPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

2. 在命令行中执行以下命令，将下载好的 `.gguf` 文件导入 LM Studio：

```bash
lms import /path/to/your/qwenpaw-xxx.gguf -c -y --user-repo AgentScope/QwenPaw-Flash
```

3. 保持 LM Studio 服务运行，在 QwenPaw 打开它的模型列表，点击 **更新模型列表**，再启用要使用的模型。

> 对于将 QwenPaw 部署在 Docker 容器中的用户，如果 LM Studio 安装在宿主机上，请确保 Docker 的网络配置允许容器访问宿主机的 LM Studio 服务（在 `docker run` 命令中添加 `--add-host=host.docker.internal:host-gateway`），并将 API 地址设置为 `http://host.docker.internal:1234/v1` 来实现连接。

## 云提供商配置

QwenPaw 当前支持的云提供商包括：

- ModelScope
- DashScope
- Aliyun Coding Plan
- OpenRouter
- OpenAI
- Azure OpenAI
- Anthropic
- Google Gemini
- DeepSeek
- Kimi
- MiniMax
- Zhipu
- SiliconFlow（硅基流动）
- OpenCode
- Volcengine（火山引擎）
- Volcengine Coding Plan
- Volcengine Agent Plan（火山引擎 Agent Plan）
- Xiaomi MiMo（小米 MiMo）
- Xiaomi MiMo Token Plan（小米 MiMo Token Plan）
- GitHub Models
- Kilo

> 由于部分供应商针对中国大陆以及其他地区提供了不同的 API 域名，请根据您所在的地区选择正确的供应商

![云供应商列表](https://img.alicdn.com/imgextra/i2/O1CN010iWs8ko7wXC3FPfU_!!6000000002852-2-tps-1600-1000.png)

为了激活云供应商，你需要进入供应商的配置页面进行配置，大部分云供应商都已经提前配置了 API 域名，您只需要输入 API Key 即可。

![配置 API Key](https://img.alicdn.com/imgextra/i1/O1CN01YQFnwvTvL5B3FPfU_!!6000000007650-2-tps-1600-1000.png)

若提供商设置中有 **测试连接**，点击它可用当前表单的地址和凭据检查连接。连接失败不一定是密钥有误，也应检查服务地址及网络。提供商检查通过，不代表账号有权使用其所有模型。

![Kilo Code 提供商设置中的连接测试成功提示](https://img.alicdn.com/imgextra/i4/O1CN015ymitubzuwJ3FPfU_!!6000000004194-2-tps-1600-1000.png)

要检查某个模型，请先保存提供商设置，再打开它的模型列表，点击目标模型对应的 **测试连接**。这次检查针对所选模型 ID，与提供商级检查不同。

![模型库中 Kilo Auto 免费模型的连接测试结果](https://img.alicdn.com/imgextra/i2/O1CN012nMBTYT0yFG3FPfU_!!6000000005975-2-tps-1600-1000.png)

如果预设的模型无法满足需求，您也可以在模型管理页面选择 **添加模型** 来添加增加新的模型，添加时需要提供 **模型 ID**（API 实际使用的模型标识，通常可以从提供商文档中获得）以及 **模型名称** （用于在界面中展示）。手动添加的模型同样可以通过 **测试连接** 来验证是否能够正常使用。

![添加模型](https://img.alicdn.com/imgextra/i2/O1CN01yYjwwEcsEZJ3FPfU_!!6000000001862-2-tps-1600-1000.png)

## 自定义供应商配置

如果预设的云提供商和本地提供商都无法满足需求，QwenPaw 还支持用户自定义提供商。

### 添加提供商

点击 **设置 → 模型 → 添加提供商**，填写提供商 ID、显示名称和基础 URL，按服务要求填写 API Key。选择端点实际使用的协议：OpenAI Chat Completions、OpenAI Responses 或 Anthropic Messages。保存后，在该提供商的模型列表中添加模型。

![添加提供商](https://img.alicdn.com/imgextra/i2/O1CN01745rhA69jSC3FPfU_!!6000000002896-2-tps-1600-1000.png)

### 配置供应商

供应商添加完成后，您可以进入该供应商的 **设置** 页面来配置该供应商的 API 访问信息，包括 _基础 URL_ 以及 _API 秘钥_ 。

![自定义供应商设置](https://img.alicdn.com/imgextra/i4/O1CN0131q7xruKgpF3FPfU_!!6000000002386-2-tps-1600-1000.png)

### 添加模型

自定义供应商配置完成后，您可以进入该供应商的 **模型** 页面，点击 **添加模型** 来添加模型，添加时需要提供 **模型 ID**（API 实际使用的模型标识）以及 **模型名称** （用于在界面中展示）。添加完成后同样可以通过 **测试连接** 来验证是否能够正常使用。

> 以 vLLM 部署为例，如果您将 vLLM 部署在 `http://localhost:8000`，并且 vLLM 中有一个路径为 `/path/to/Qwen3.5` 的模型，那么您可以添加一个自定义提供商，设置 API 兼容模式为 OpenAI `chat.completions`，基础 URL 设置为 `http://localhost:8000/v1`，然后在该提供商下添加一个模型，模型 ID 填写 `/path/to/Qwen3.5`，模型名称可以自定义为 `Qwen3.5`，添加完成后测试连接，如果一切配置正确，就可以在 QwenPaw 中使用这个 vLLM 模型了。

## 选择模型

在 **设置 → 模型 → 默认模型** 中选择 **对话模型**，选择后自动保存。**决策模型** 是独立配置，不是第二个对话模型。

![全局对话模型选择器](https://img.alicdn.com/imgextra/i3/O1CN01zlN7yTjh7hB3FPfU_!!6000000002887-2-tps-1600-1000.png)

要为某个会话单独选模，请使用聊天输入区的模型选择器。清除会话选择后会重新继承智能体的模型；不会修改智能体或全局默认值。

![聊天输入区的会话模型选择器](https://img.alicdn.com/imgextra/i1/O1CN01eNUg5R1qLmG3FPfU_!!6000000002950-2-tps-1600-1000.png)

## 模型配置进阶

### 模型配置文件

QwenPaw 中所有提供商的配置都会保存在 `$QWENPAW_SECRET_DIR/providers` 文件夹中（默认 `~/.qwenpaw.secret/providers`），内置的提供商配置会放在 `builtin` 目录下，而用户添加的自定义提供商配置会放在 `custom` 目录下，每个提供商会对应一个 JSON 文件来保存其配置信息，文件名为该提供商的 ID，例如提供商 ID 为 `Qwen` 的提供商的配置文件为 `Qwen.json`，文件内容包含该提供商的 API 访问信息以及模型列表等信息。但不建议普通用户直接修改这些配置文件，以免造成不必要的错误，另外对配置文件的修改需要重启 QwenPaw 后才会生效。

### 本地模型

手动导入 GGUF 时，先找到插件的数据目录。下表中的相对路径以 `$QWENPAW_WORKING_DIR`（默认 `~/.qwenpaw`）为起点。

| 使用情况                 | 数据目录                              |
| ------------------------ | ------------------------------------- |
| 首次使用本地插件         | `plugin-data/local-llamacpp/runtime/` |
| 从旧版升级，已有本地模型 | 沿用原目录，默认为 `local_models/`    |
| 已配置插件的 `data_dir`  | 使用该配置指定的目录                  |

在数据目录中创建 `models/组织名/模型名/`，将 GGUF 放进去。例如 `models/Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B.gguf`。刷新 QwenPaw Local 模型列表后，即可启动该模型。

同一数据目录下，`bin/` 存放 llama.cpp 运行库，`logs/llama-server.log` 记录服务日志。

### 生成参数

由于不同模型以及不同任务可能对生成参数有不同的需求（例如 `temperature`， `top_p`， `max_tokens`），QwenPaw 支持在供应商设置中配置生成参数。进入供应商的 **设置** 页面，展开**进阶配置**，并在生成参数配置文本框中输入对应的参数配置，参数配置需要符合 JSON 格式，例如：

```json
{
  "temperature": 0.7,
  "top_p": 0.9,
  "max_tokens": 4096
}
```

配置完成后点击 **保存**，QwenPaw 就会在使用该供应商的模型进行生成时自动带上这些参数配置了。

![生成参数](https://img.alicdn.com/imgextra/i1/O1CN01B6plEcVl8SE3FPfU_!!6000000003566-2-tps-1600-1000.png)
