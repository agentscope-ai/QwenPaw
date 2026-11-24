# Models

Before using QwenPaw, you need to configure at least one available model. QwenPaw supports multiple model providers, which you can configure and manage on the **Settings -> Models** page in the left sidebar.

![Global defaults and cloud providers](https://img.alicdn.com/imgextra/i3/O1CN01HJqMiEzR7MJ3FPfU_!!6000000005835-2-tps-1600-1000.png)

QwenPaw supports various LLM providers:

- **Local Providers** (llama.cpp / Ollama / LM Studio)
- **Cloud Providers** (usually require an API Key)
- **Custom Providers** (if the preset local and cloud providers do not meet your needs)

Currently supported local providers include:

- [QwenPaw Local (llama.cpp)](https://github.com/ggml-org/llama.cpp)
- [Ollama](https://ollama.com/)
- [LM Studio](https://lmstudio.ai/)

QwenPaw Local is available as an optional plugin. Install Ollama or LM Studio separately to use either provider.

QwenPaw also provides the QwenPaw-Flash series for local deployment. It includes 2B, 4B, and 9B variants, with original, 4-bit, and 8-bit versions for different VRAM and performance requirements. These models are open-sourced on [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) and [Hugging Face](https://huggingface.co/agentscope-ai/models). The following sections explain how to use QwenPaw-Flash with each local provider.

## QwenPaw Local (llama.cpp) Configuration

> QwenPaw Local is currently still in the testing phase, and there may be issues with stability and GPU compatibility. If you are looking for a more stable local model experience or need GPU acceleration, it is recommended to use Ollama or LM Studio as your local model provider in the short term.

On a fresh installation, **Settings → Models → Local & Custom** lists Ollama and LM Studio. These connect to services that you run separately. To have QwenPaw manage llama.cpp and its GGUF files instead:

![Local & Custom before installing QwenPaw Local](https://img.alicdn.com/imgextra/i3/O1CN01jnH9eVHuqvF3FPfU_!!6000000002438-2-tps-1600-1000.png)

1. Open **Settings → Extension → Plugins → Official Plugins** and install **QwenPaw Local** (`local-llamacpp`). If it is already installed, check that it is enabled under **Installed Plugins**.
2. Return to **Models → Local & Custom** and open the model manager on the **QwenPaw Local** card. Click **Install llama.cpp** if the inference engine is missing. Installing the plugin does not download the engine or a model.
3. Download a recommended model, or choose ModelScope or Hugging Face and enter a GGUF repository ID. Already have the weights? [Import your GGUF files](./models#Local-Models) instead of downloading them again.
4. Click **Start** beside the downloaded model. Flash sets the default chat model; Piccolo sets the default decision model. The two share one server: wait for active requests to finish before switching. **Stop** shuts down the server without deleting the weights.

When QwenPaw restarts, it tries to restore a previously started local model selected by an enabled agent. If you use only cloud models, llama.cpp stays stopped.

### Local Piccolo decision models

Under **Decision models** in QwenPaw Local, choose a recommended BF16 or Q8_0 model for your machine's memory. Download it and select **Start**. For Q4_K_M, use the custom download option and enter a GGUF repository ID, such as `agentscope-ai/Piccolo-4B-Q4_K_M` on Hugging Face or `AgentScope/Piccolo-4B-Q4_K_M` on ModelScope.

Under **Models → Default models → Decision model**, check that Piccolo is selected. Then configure the agent for the feature you want to use.

- **Tool review**. Choose **Decision Model Mode** in the agent's security settings and enable tool review in the conversation.
- **Context compaction**. Turn on automatic context compaction in the agent's context settings, then select **Enable decision model compaction**.

## Ollama Configuration

Before using Ollama, you need to install the latest version of [Ollama](https://ollama.com/download) on your machine, download at least one model, and set the Context Length to at least 32k on the settings page.

![Ollama Settings](https://img.alicdn.com/imgextra/i2/O1CN016SaCfhrrKrI3FPfU_!!6000000007523-2-tps-1600-1000.png)

To verify that Ollama is working properly, go to the **Settings** page of the QwenPaw Ollama provider and click the **Test Connection** button.

> For users deploying QwenPaw in a Docker container, if Ollama is installed on the host machine, ensure that the Docker network configuration allows the container to access the host's Ollama service (add `--add-host=host.docker.internal:host-gateway` to the `docker run` command), and set the API address to `http://host.docker.internal:11434`.

If you want to use QwenPaw-Flash with Ollama, it is recommended to choose a `Q8_0` or `Q4_K_M` quantized variant and import it with the following steps:

1. Download a suitable quantized QwenPaw-Flash model from [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) or [Hugging Face](https://huggingface.co/agentscope-ai/models), for example `AgentScope/QwenPaw-Flash-4B-Q4_K_M`.

ModelScope CLI:

```bash
modelscope download --model AgentScope/QwenPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

Hugging Face CLI:

```bash
hf download agentscope-ai/QwenPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

2. Create a text file named `qwenpaw-flash.txt` and replace `/path/to/your/qwenpaw-xxx.gguf` with the absolute path of the downloaded `.gguf` file:

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

3. Run the following command in your terminal to import the model into Ollama:

```bash
ollama create qwenpaw-flash -f qwenpaw-flash.txt
```

4. Open the Ollama card’s model list and click **Update model list** (refresh icon). Enable the model you want to use; syncing the catalog does not download weights into QwenPaw.

## LM Studio Configuration

Before using LM Studio, you need to install the latest version of [LM Studio](https://lmstudio.ai/download) on your machine.

By default, LM Studio does not enable the model API service. After installing LM Studio and downloading models, go to **Developer -> Local Server** to start the local model service and note the API address, which defaults to `http://localhost:1234`.

![LM Studio Local Server](https://gw.alicdn.com/imgextra/i3/O1CN01kLXu3D1VwRF3lokZz_!!6000000002717-2-tps-1654-1256.png)

To ensure a good experience in QwenPaw, set the **Default Context Length** to at least 32768 in **Settings -> Model Defaults**, and enable "When applicable, separate `reasoning_content` and `content` in API responses" in **Settings -> Developer -> Experimental Settings**.

![LM Studio Context Length](https://gw.alicdn.com/imgextra/i4/O1CN011jc2q71hc51etcf7x_!!6000000004297-2-tps-1654-1256.png)

![LM Studio Reasoning Content](https://gw.alicdn.com/imgextra/i4/O1CN01dInPGl1oDX6nOH0Wh_!!6000000005191-2-tps-1654-1256.png)

After completing the above LM Studio configuration, go to the **Settings** page of the QwenPaw LM Studio provider and enter the LM Studio API address, which can be found on the **Developer -> Local Server** page. Be sure to add the `/v1` suffix, e.g., `http://localhost:1234/v1`.

If you want to use QwenPaw-Flash with LM Studio, it is also recommended to choose a `Q8_0` or `Q4_K_M` quantized variant and import it with the following steps:

1. Download a suitable quantized QwenPaw-Flash model from [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) or [Hugging Face](https://huggingface.co/agentscope-ai/models), for example `AgentScope/QwenPaw-Flash-4B-Q4_K_M`.

ModelScope CLI:

```bash
modelscope download --model AgentScope/QwenPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

Hugging Face CLI:

```bash
hf download agentscope-ai/QwenPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

2. Run the following command to import the downloaded `.gguf` file into LM Studio:

```bash
lms import /path/to/your/qwenpaw-xxx.gguf -c -y --user-repo AgentScope/QwenPaw-Flash
```

3. With the LM Studio server running, open its model list in QwenPaw, click **Update model list**, then enable the model you want to use.

> For users deploying QwenPaw in a Docker container, if LM Studio is installed on the host machine, ensure that the Docker network configuration allows the container to access the host's LM Studio service (add `--add-host=host.docker.internal:host-gateway` to the `docker run` command), and set the API address to `http://host.docker.internal:1234/v1`.

## Cloud Provider Configuration

Currently supported cloud providers include:

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
- SiliconFlow
- OpenCode
- Volcengine
- Volcengine Coding Plan
- Volcengine Agent Plan
- Xiaomi MiMo
- Xiaomi MiMo Token Plan
- GitHub Models
- Kilo

> Some providers offer different base URLs for Mainland China and other regions. Please select the correct provider based on your location.

![Cloud Provider List](https://img.alicdn.com/imgextra/i3/O1CN01HJqMiEzR7MJ3FPfU_!!6000000005835-2-tps-1600-1000.png)

To activate a cloud provider, go to the provider's configuration page. Most cloud providers have pre-configured base URL; you only need to enter your API Key.

![Configure API Key](https://img.alicdn.com/imgextra/i3/O1CN015dnga0znQtK3FPfU_!!6000000001354-2-tps-1600-1000.png)

If the provider settings offer **Test Connection**, use it to check the endpoint with the credentials currently in the form. A failure can also indicate an incorrect address or a network problem. A successful provider check does not establish access to every model.

![Successful connection test in Kilo Code provider settings](https://img.alicdn.com/imgextra/i3/O1CN01fDRsmAAoSaF3FPfU_!!6000000007117-2-tps-1600-1000.png)

To check a particular model, save the provider settings, open its model list, and use **Test Connection** on the target row. This check uses the selected model ID, unlike the provider-level check.

![Connection test result for Kilo Auto in the model library](https://img.alicdn.com/imgextra/i3/O1CN010eaKLd6b29E3FPfU_!!6000000002245-2-tps-1600-1000.png)

If the preset models do not meet your needs, you can also click **Add Model** on the model management page to add new models. When adding, you need to provide the **Model ID** (the identifier used by the API, usually found in the provider's documentation) and the **Model Name** (for display in the UI). Manually added models can also be tested using the **Test Connection** button.

![Add Model](https://img.alicdn.com/imgextra/i1/O1CN01mIFvyZ6D8qI3FPfU_!!6000000008163-2-tps-1600-1000.png)

## Custom Provider Configuration

If the preset cloud and local providers do not meet your needs, QwenPaw also supports custom providers.

### Add Provider

In **Settings → Models**, click **Add Provider**. Enter a provider ID, display name, and base URL. Supply an API key if the service requires one. Match the protocol to the endpoint: OpenAI Chat Completions, OpenAI Responses, or Anthropic Messages. After saving, open the provider’s model list to add a model.

![Add Provider](https://img.alicdn.com/imgextra/i2/O1CN01otwziNcxq0J3FPfU_!!6000000005084-2-tps-1600-1000.png)

### Configure Provider

After adding a provider, go to its **Settings** page to configure the API access information, including _Base URL_ and _API Key_.

![Custom Provider Settings](https://img.alicdn.com/imgextra/i2/O1CN01LP0rLsyewHH3FPfU_!!6000000001256-2-tps-1600-1000.png)

### Add Model

After configuring a custom provider, go to its **Models** page and click **Add Model**. When adding, you need to provide the **Model ID** (the identifier used by the API) and **Model Name** (for display in the UI). After adding, you can also use **Test Connection** to verify if the model is working properly.

> For example, if you deploy vLLM at `http://localhost:8000` and have a model at `/path/to/Qwen3.5`, you can add a custom provider, set the API compatibility mode to OpenAI `chat.completions`, set the Base URL to `http://localhost:8000/v1`, then add a model under this provider with Model ID `/path/to/Qwen3.5` and Model Name `Qwen3.5`. After testing the connection, if everything is configured correctly, you can use this vLLM model in QwenPaw.

## Selecting a Model

Under **Settings → Models → Default models**, choose a **Chat model**. The selection is saved immediately. **Decision model** is a separate slot, not a second chat model.

![Global chat model selector](https://img.alicdn.com/imgextra/i2/O1CN019X2i5pZzxKD3FPfU_!!6000000002643-2-tps-1600-1000.png)

To override the model for one conversation, use the model selector in the chat input area. Clear that selection to inherit the agent’s model again. This does not change the agent or global defaults.

![Conversation model selector in the chat input](https://img.alicdn.com/imgextra/i4/O1CN01pq8rx72eaSB3FPfU_!!6000000001688-2-tps-1600-1000.png)

## Advanced Model Configuration

### Model Configuration Files

All provider configurations in QwenPaw are saved in the `$QWENPAW_SECRET_DIR/providers` folder (default `~/.qwenpaw.secret/providers`). Built-in provider configurations are in the `builtin` directory, and user-added custom provider configurations are in the `custom` directory. Each provider has a corresponding JSON file named after its ID, e.g., the configuration file for a provider with ID `Qwen` is `Qwen.json`. The file contains the provider's API access information and model list. It is not recommended for regular users to modify these files directly to avoid unnecessary errors. Also, changes to the configuration files require restarting QwenPaw to take effect.

### Local Models

To import a GGUF file, first find the plugin’s data directory. Relative paths below start at `$QWENPAW_WORKING_DIR` (default `~/.qwenpaw`).

| Setup                               | Data directory                                      |
| ----------------------------------- | --------------------------------------------------- |
| First time using the local plugin   | `plugin-data/local-llamacpp/runtime/`               |
| Upgraded with existing local models | Your original directory, `local_models/` by default |
| Plugin has a configured `data_dir`  | The directory specified by that setting             |

In the data directory, create `models/owner/model/` and copy the GGUF file there. For example, use `models/Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B.gguf`. Refresh the QwenPaw Local model list, then start the model.

The same data directory contains the llama.cpp runtime in `bin/` and the server log in `logs/llama-server.log`.

### Generation Parameters

Since different models and tasks may require different generation parameters (such as `temperature`, `top_p`, `max_tokens`), QwenPaw supports configuring generation parameters in the provider settings. Go to the provider's **Settings** page, expand **Advanced Configuration**, and enter the parameter configuration in JSON format, for example:

```json
{
  "temperature": 0.7,
  "top_p": 0.9,
  "max_tokens": 4096
}
```

After configuring, click **Save**. QwenPaw will automatically include these parameters when generating with models from this provider.

![Generation Parameters](https://img.alicdn.com/imgextra/i1/O1CN0132aA21fW9RB3FPfU_!!6000000007667-2-tps-1600-1000.png)
