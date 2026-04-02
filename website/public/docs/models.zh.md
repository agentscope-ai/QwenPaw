# 模型

在使用 CoPaw 之前，您需要配置至少一个可用模型，CoPaw 支持多种模型提供商，您可以在页面左侧边栏的 **设置 -> 模型** 页面进行配置和管理。

![设置模型](https://gw.alicdn.com/imgextra/i3/O1CN01MmM8iv1rcfh95wdn3_!!6000000005652-2-tps-3394-1880.png)

CoPaw 支持多种 LLM 提供商：

- **本地提供商**（llama.cpp / Ollama / LM Studio）
- **云提供商**（一般需要 API Key）
- **自定义提供商**（如果预设的本地和云提供商无法满足您的需求）

CoPaw 当前支持的本地供应商包括：

- [CoPaw Local (llama.cpp)](https://github.com/ggml-org/llama.cpp)
- [Ollama](https://ollama.com/)
- [LM Studio](https://lmstudio.ai/)

其中 CoPaw Local (llama.cpp) 内置在 CoPaw 中，无需额外安装其他软件，Ollama 和 LM Studio 需要用户提前安装好对应的软件。

CoPaw 官方还提供了适合本地部署的 CoPaw-Flash 系列模型，包含 2B、4B 和 9B 三个版本；除原始模型外，还提供 4 bit 和 8 bit 量化版本，适合不同的显存环境和性能需求。这些模型已经在 [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) 和 [Hugging Face](https://huggingface.co/agentscope-ai/models) 上开源，下面分别介绍如何在三种本地供应商中使用 CoPaw-Flash。

## CoPaw Local (llama.cpp) 配置

> CoPaw Local 目前仍处于测试阶段，稳定性以及对 GPU 的兼容性存在问题，如果追求稳定或是需要使用 GPU 加速，短期内建议使用 Ollama 或 LM Studio 作为本地模型提供商。

CoPaw Local 是基于 llama.cpp 的本地模型提供商，可以进入 **模型** 界面进行配置和管理。

![CoPaw Local 提供商](https://gw.alicdn.com/imgextra/i4/O1CN01OAi8oN1acoLWlsm6B_!!6000000003351-2-tps-2410-1634.png)

初次配置 CoPaw Local 时，您需要先下载 llama.cpp 运行库，点击 **下载 llama.cpp** 按钮，CoPaw 会自动下载并配置好 llama.cpp 运行库，下载完成后您就可以使用 CoPaw Local 提供商了。

![下载 llama.cpp](https://gw.alicdn.com/imgextra/i3/O1CN01Nqs9Cg1Vp6uA2WdiM_!!6000000002701-2-tps-1270-874.png)

CoPaw 团队专门训练了一系列适合本地部署的小模型（CoPaw-Flash 系列），会自动根据您当前的设备（CPU / NVIDIA GPU / Apple M 系列芯片）为您推荐适合的模型版本。如果您希望使用 CoPaw-Flash，直接在这里选择合适的版本下载并启动即可；如果您希望使用其他模型，也可以通过填写 _模型仓库 ID_ 以及 _下载源_ 来添加其他模型，模型仓库 ID 是指模型在 ModelScope / Hugging Face 等模型仓库中的标识，例如 `Qwen/Qwen3-0.6B-GGUF`，下载源是指下载模型的途径，目前支持 ModelScope 和 Hugging Face 两种下载源。

![下载模型](https://gw.alicdn.com/imgextra/i2/O1CN01IF2OXz1c99w9W8XGU_!!6000000003557-2-tps-1226-1202.png)

模型下载完成后就可以点击 **启动** 按钮来启动该模型，不同大小的模型启动耗时可能有差异，请耐心等待，启动后 CoPaw 会自动将全局默认模型切换为该模型。同一时刻只能启动一个模型，启动其他模型时会自动关闭当前正在运行的模型。

![启动模型](https://gw.alicdn.com/imgextra/i1/O1CN01NSNFUN1I21RynZwGy_!!6000000000834-2-tps-1224-1194.png)

在暂时不需要使用模型时，您可以选择 **停止** 模型来停止该模型的服务。

![停止模型](https://gw.alicdn.com/imgextra/i4/O1CN01ewNXXD1nMrYq8zvuC_!!6000000005076-2-tps-1230-1284.png)

CoPaw Local 会自动记录模型启动状态，如果您在关闭 CoPaw 进程时，CoPaw Local 模型正在运行，下次打开时会自动尝试重新启动上次使用的模型，从而无需每次启动 CoPaw 后都手动启动模型。

## Ollama 配置

在使用 Ollama 之前，您需要先在机器上安装最新版 [Ollama](https://ollama.com/download)，至少下载一个模型，并且在设置页面中将 Context Length 设置为至少 32k。

![Ollama 设置](https://gw.alicdn.com/imgextra/i4/O1CN01pWWxlV1QiApLwDzbU_!!6000000002009-2-tps-1912-1510.png)

为了验证 Ollama 是否能够正常使用，可以进入 CoPaw Ollama 提供商的 **设置** 页面，点击 **测试连接** 按钮来验证 CoPaw 是否能够连接到 Ollama 服务。

> 对于将 CoPaw 部署在 Docker 容器中的用户，如果 Ollama 安装在宿主机上，请确保 Docker 的网络配置允许容器访问宿主机的 Ollama 服务（在 `docker run` 命令中添加 `--add-host=host.docker.internal:host-gateway`），并将 API 地址设置为 `http://host.docker.internal:11434` 来实现连接。

如果您希望在 Ollama 中使用 CoPaw-Flash，建议选择 `Q8_0` 或 `Q4_K_M` 量化版本，并按以下步骤导入：

1. 从 [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) 或 [Hugging Face](https://huggingface.co/agentscope-ai/models) 下载合适的 CoPaw-Flash 量化模型，例如 `AgentScope/CoPaw-Flash-4B-Q4_K_M`。

ModelScope CLI：

```bash
modelscope download --model AgentScope/CoPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

Hugging Face CLI：

```bash
hf download agentscope-ai/CoPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

2. 创建一个文本文件 `copaw-flash.txt`，并将 `/path/to/your/copaw-xxx.gguf` 替换为下载后的 `.gguf` 文件绝对路径：

```text
FROM /path/to/your/copaw-xxx.gguf
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
ollama create copaw-flash -f copaw-flash.txt
```

4. 回到 CoPaw 的 Ollama 提供商模型页面，点击 **自动获取模型** 即可将该模型加入 CoPaw。

Ollama 安装配置完成后，可以进入 CoPaw Ollama 提供商的 **模型** 页面，点击 **自动获取模型** 按钮以获得当前可用的 Ollama 模型列表，获取完成后可以进一步点击 **测试连接** 来验证模型是否能够正常使用。

![Ollama 模型列表](https://gw.alicdn.com/imgextra/i3/O1CN01esQyTg1eSyIlpRK69_!!6000000003871-2-tps-1208-1322.png)

## LM Studio 配置

在使用 LM Studio 之前，您需要先在机器上安装最新版 [LM Studio](https://lmstudio.ai/download)。

LM Studio 默认不会开启模型 API 服务，因此在 LM Studio 安装完成并下载模型后，您需要进入 **Developer -> Local Server** 页面，启动本地模型服务，并记录下 API 地址，默认为 `http://localhost:1234`。

![LM Studio 本地服务](https://gw.alicdn.com/imgextra/i3/O1CN01kLXu3D1VwRF3lokZz_!!6000000002717-2-tps-1654-1256.png)

为了保证 CoPaw 中的使用体验，需要在 LM Studio 的 **Settings -> Model Defaults** 页面中将 **Default Context Length** 设置为至少 32768，并在 **Settings -> Developer** 页面中将 **Experimental Settings** 中的 "When applicable, separate `reasoning_content` and `content` in API responses" 选项打开。

![LM Studio 上下文长度](https://gw.alicdn.com/imgextra/i4/O1CN011jc2q71hc51etcf7x_!!6000000004297-2-tps-1654-1256.png)

![LM Studio 思考内容解析](https://gw.alicdn.com/imgextra/i4/O1CN01dInPGl1oDX6nOH0Wh_!!6000000005191-2-tps-1654-1256.png)

上述 LM Studio 配置完成后，可以进入 CoPaw LM Studio 提供商的 **设置** 页面，输入 LM Studio 的 API 地址，该地址可以从 LM Studio 的 **Developer -> Local Server** 页面获取，但注意要后缀 `/v1`，例如 `http://localhost:1234/v1`。

如果您希望在 LM Studio 中使用 CoPaw-Flash，建议同样选择 `Q8_0` 或 `Q4_K_M` 量化版本，并按以下步骤导入：

1. 从 [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) 或 [Hugging Face](https://huggingface.co/agentscope-ai/models) 下载合适的 CoPaw-Flash 量化模型，例如 `AgentScope/CoPaw-Flash-4B-Q4_K_M`。

ModelScope CLI：

```bash
modelscope download --model AgentScope/CoPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

Hugging Face CLI：

```bash
hf download agentscope-ai/CoPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

2. 在命令行中执行以下命令，将下载好的 `.gguf` 文件导入 LM Studio：

```bash
lms import /path/to/your/copaw-xxx.gguf -c -y --user-repo AgentScope/CoPaw-Flash
```

3. 回到 CoPaw 的 LM Studio 提供商模型页面，点击 **自动获取模型** 即可将该模型加入 CoPaw。

后续流程与 Ollama 相同，点击 **测试连接** 按钮来验证 CoPaw 是否能够连接到 LM Studio 服务，如果连接成功，就可以进入 LM Studio 模型管理页面，点击 **自动获取模型** 来获取当前 LM Studio 中可用的模型列表，获取完成后可以进一步点击 **测试连接** 来验证模型是否能够正常使用。

> 对于将 CoPaw 部署在 Docker 容器中的用户，如果 LM Studio 安装在宿主机上，请确保 Docker 的网络配置允许容器访问宿主机的 LM Studio 服务（在 `docker run` 命令中添加 `--add-host=host.docker.internal:host-gateway`），并将 API 地址设置为 `http://host.docker.internal:1234/v1` 来实现连接。

## 云提供商配置

CoPaw 当前支持的云提供商包括：

- ModelScope
- DashScope
- Aliyun Coding Plan
- Zhipu（BigModel）
- Zhipu Coding Plan（BigModel）
- Zhipu（Z.AI）
- Zhipu Coding Plan（Z.AI）
- OpenAI
- Azure OpenAI
- Anthropic
- Google Gemini
- MiniMax

> 由于部分供应商针对中国大陆以及其他地区提供了不同的 API 域名，请根据您所在的地区选择正确的供应商

对于 Zhipu 提供商，CoPaw 内置了以下几种配置：

- `zhipu-cn`：`https://open.bigmodel.cn/api/paas/v4`
- `zhipu-cn-codingplan`：`https://open.bigmodel.cn/api/coding/paas/v4`
- `zhipu-intl`：`https://api.z.ai/api/paas/v4`
- `zhipu-intl-codingplan`：`https://api.z.ai/api/coding/paas/v4`

预设模型为 `glm-5`、`glm-5.1`、`glm-5-turbo` 和 `glm-5v-turbo`。
其中 Coding Plan 端点主要用于支持的 Coding 工具及对应额度场景，
普通 API 调用请使用标准 API 端点。

![云供应商列表](https://gw.alicdn.com/imgextra/i3/O1CN01EoK2LV2AH7lFM4GJu_!!6000000008177-2-tps-3402-1942.png)

为了激活云供应商，你需要进入供应商的配置页面进行配置，大部分云供应商都已经提前配置了 API 域名，您只需要输入 API Key 即可。

![配置 API Key](https://gw.alicdn.com/imgextra/i4/O1CN01pbLeu81jIVKRoGrSk_!!6000000004525-2-tps-1058-772.png)

填入 API Key 后，点击 **测试连接** 按钮，系统会自动验证 API Key 是否正确（仅部分供应商支持）。

![测试连接结果](https://gw.alicdn.com/imgextra/i1/O1CN01dGL7cJ1jH88mTpW9z_!!6000000004522-2-tps-1088-946.png)

云供应商配置完成后可以进一步检测模型是否能够使用，云供应商内已经预设了一系列常用模型，你可以点击供应商的模型管理页面中某个具体模型的 **测试连接** 按钮，系统会自动验证模型是否能够正常使用。

![模型连接测试结果](https://gw.alicdn.com/imgextra/i3/O1CN01aAyd2L1N77wX0OvtY_!!6000000001522-2-tps-1150-1154.png)

如果预设的模型无法满足需求，您也可以在模型管理页面选择 **添加模型** 来添加增加新的模型，添加时需要提供 **模型 ID**（API 实际使用的模型标识，通常可以从提供商文档中获得）以及 **模型名称** （用于在界面中展示）。手动添加的模型同样可以通过 **测试连接** 来验证是否能够正常使用。

![添加模型](https://gw.alicdn.com/imgextra/i1/O1CN01FBIdEH1ud4tTIHpEZ_!!6000000006059-2-tps-1148-1342.png)

## 自定义供应商配置

如果预设的云提供商和本地提供商都无法满足需求，CoPaw 还支持用户自定义提供商。

### 添加提供商

您可以使用 **设置 -> 模型 -> 提供商** 右上角的 **添加提供商** 来添加一个新的提供商，添加时需要提供 **提供商 ID**（用于 CoPaw 内部索引）以及 **提供商名称** （用于在界面中展示），并选择该供应商的 API 兼容模式（目前支持 OpenAI `chat.completions` 以及 Anthropic `messages` 两种）。添加完成后您可以像云提供商一样在该提供商下添加模型，并且在聊天等场景中选择使用该提供商的模型。

![添加提供商](https://gw.alicdn.com/imgextra/i1/O1CN01UE3Vbu1hGYPWlzpps_!!6000000004250-2-tps-3394-1882.png)

### 配置供应商

供应商添加完成后，您可以进入该供应商的 **设置** 页面来配置该供应商的 API 访问信息，包括 _基础 URL_ 以及 _API 秘钥_ 。

![自定义供应商设置](https://gw.alicdn.com/imgextra/i1/O1CN01UE3Vbu1hGYPWlzpps_!!6000000004250-2-tps-3394-1882.png)

### 添加模型

自定义供应商配置完成后，您可以进入该供应商的 **模型** 页面，点击 **添加模型** 来添加模型，添加时需要提供 **模型 ID**（API 实际使用的模型标识）以及 **模型名称** （用于在界面中展示）。添加完成后同样可以通过 **测试连接** 来验证是否能够正常使用。

> 以 vLLM 部署为例，如果您将 vLLM 部署在 `http://localhost:8000`，并且 vLLM 中有一个路径为 `/path/to/Qwen3.5` 的模型，那么您可以添加一个自定义提供商，设置 API 兼容模式为 OpenAI `chat.completions`，基础 URL 设置为 `http://localhost:8000/v1`，然后在该提供商下添加一个模型，模型 ID 填写 `/path/to/Qwen3.5`，模型名称可以自定义为 `Qwen3.5`，添加完成后测试连接，如果一切配置正确，就可以在 CoPaw 中使用这个 vLLM 模型了。

## 选择模型

配置好的模型供应商以及模型会显示在 **设置 -> 模型 -> 默认 LLM** 的列表中，您可以选择一个模型作为全局默认模型，点击模型右侧的 **保存** 按钮即可，在该页面设置的模型会作为全局默认模型被 CoPaw 使用，如果您在某些场景（例如聊天）中没有指定模型，CoPaw 就会使用这里设置的默认模型。

![默认模型设置](https://gw.alicdn.com/imgextra/i4/O1CN01NH2eBZ1UBQyhucWdj_!!6000000002479-2-tps-3388-808.png)

由于不同任务所需的模型能力存在差别，CoPaw 也支持在不同聊天中使用不同的模型，你可以在 **聊天** 页面右上角的下拉菜单中选择合适的供应商和模型，但该设置仅对当前使用的智能体以及聊天生效。如果没有在聊天页面配置供应商或者模型，CoPaw 就会使用全局默认模型。

![聊天模型设置](https://gw.alicdn.com/imgextra/i3/O1CN01BjQlqH1eC1eC7xNm8_!!6000000003834-2-tps-3402-1768.png)

## 模型配置进阶

### 模型配置文件

CoPaw 中所有提供商的配置都会保存在 `$COPAW_SECRET_DIR/providers` 文件夹中（默认 `~/.copaw.secret/providers`），内置的提供商配置会放在 `builtin` 目录下，而用户添加的自定义提供商配置会放在 `custom` 目录下，每个提供商会对应一个 JSON 文件来保存其配置信息，文件名为该提供商的 ID，例如提供商 ID 为 `Qwen` 的提供商的配置文件为 `Qwen.json`，文件内容包含该提供商的 API 访问信息以及模型列表等信息。但不建议普通用户直接修改这些配置文件，以免造成不必要的错误，另外对配置文件的修改需要重启 CoPaw 后才会生效。

### 本地模型

如果使用了 CoPaw Local (llama.cpp) 提供商，CoPaw 会在 `$COPAW_WORKING_DIR/local_models` 文件夹中（默认 `~/.copaw/local_models`）中保存 llama.cpp 相关的运行库以及模型文件，其中运行库会保存在 `$COPAW_WORKING_DIR/local_models/bin` 目录下，而下载的模型会保存在 `$COPAW_WORKING_DIR/local_models/models` 目录下，每个模型会对应一个文件夹，文件夹名称为该模型的 ID，例如模型 ID 为 `Qwen/Qwen3-0.6B-GGUF` 的模型文件夹为 `$COPAW_WORKING_DIR/local_models/models/Qwen/Qwen3-0.6B-GGUF`，模型文件夹内会保存该模型的 GGUF 文件以及一些模型元信息文件。

如果用户对 llama.cpp 有更深入的使用需求（例如需要使用 llama.cpp 针对特定硬件的加速能力），可以自行编译拥有对应能力的 llama.cpp，并替换 `bin` 目录下的所有文件，CoPaw Local 会自动使用用户替换后的 llama.cpp 运行库来启动模型。

如果用户需要使用其他来源的 GGUF 模型文件，可以在 `models` 目录下创建 `组织名/模型名` 结构的子文件夹，然后将 `GGUF` 文件保存到该文件夹中，然后刷新 CoPaw Local 的模型列表，就可以在 CoPaw Local 的模型列表中看到该模型了（例如将 `Qwen3-0.6B.gguf` 模型文件保存到 `$COPAW_WORKING_DIR/local_models/models/Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B.gguf`）

### 生成参数

由于不同模型以及不同任务可能对生成参数有不同的需求（例如 `temperature`， `top_p`， `max_tokens`），CoPaw 支持在供应商设置中配置生成参数。进入供应商的 **设置** 页面，展开**进阶配置**，并在生成参数配置文本框中输入对应的参数配置，参数配置需要符合 JSON 格式，例如：

```json
{
  "temperature": 0.7,
  "top_p": 0.9,
  "max_tokens": 4096
}
```

配置完成后点击 **保存**，CoPaw 就会在使用该供应商的模型进行生成时自动带上这些参数配置了。

![生成参数](https://gw.alicdn.com/imgextra/i2/O1CN01et3R371uamugLZiT0_!!6000000006054-2-tps-1078-1732.png)
