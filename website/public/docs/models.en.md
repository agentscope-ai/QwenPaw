# Models

Before using QwenPaw, you need to configure at least one available model. QwenPaw supports multiple model providers, which you can configure and manage on the **Settings -> Models** page in the left sidebar.

![Settings Models](https://img.alicdn.com/imgextra/i2/O1CN01cmjcv31YO2MD9GzGn_!!6000000003048-2-tps-3810-2064.png)

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

Open **Settings → Models**. If QwenPaw Local is missing, open **Plugin Manager**. Install **QwenPaw Local** (`local-llamacpp`) from **Official Plugins**, or enable it under **Installed Plugins** if already installed. Return to Models.

![QwenPaw Local Provider](https://img.alicdn.com/imgextra/i4/O1CN01BBeBIR1zXeIQfAK8b_!!6000000006724-2-tps-3810-2064.png)

Open the QwenPaw Local model manager. If the runtime is missing, click **Install llama.cpp**.

![Download llama.cpp](https://img.alicdn.com/imgextra/i1/O1CN01VhSJKd1yhtWZ0SgYc_!!6000000006611-2-tps-1530-1290.png)

Download a recommended model, such as QwenPaw-Flash for chat. To download another GGUF model, select ModelScope or Hugging Face and enter its repository ID, such as `Qwen/Qwen3-0.6B-GGUF`. To import a GGUF file you already have, see [Local Models](./models#Local-Models).

![Download Model](https://img.alicdn.com/imgextra/i4/O1CN01ualQNr1KMkbpBiuTa_!!6000000001150-2-tps-1342-1680.png)

Click **Start** next to the model. Starting Flash sets it as the default chat model. Starting Piccolo sets it as the default decision model. llama.cpp runs one model at a time. Wait for active requests to finish before switching.

![Start Model](https://img.alicdn.com/imgextra/i4/O1CN019nuWG21Zy36HLYRWR_!!6000000003262-2-tps-1344-1678.png)

Click **Stop** to shut down the local server. Downloaded models stay on disk.

![Stop Model](https://img.alicdn.com/imgextra/i2/O1CN01fkeHhn1onG0ItKjT5_!!6000000005269-2-tps-1358-1786.png)

When QwenPaw restarts, it tries to restore a previously started local model selected by an enabled agent. If you use only cloud models, llama.cpp stays stopped.

## Ollama Configuration

Before using Ollama, you need to install the latest version of [Ollama](https://ollama.com/download) on your machine, download at least one model, and set the Context Length to at least 32k on the settings page.

![Ollama Settings](https://gw.alicdn.com/imgextra/i4/O1CN01pWWxlV1QiApLwDzbU_!!6000000002009-2-tps-1912-1510.png)

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

4. Go back to the QwenPaw Ollama provider page and click **Discover Models** to add the model to QwenPaw.

After installing and configuring Ollama, go to the **Models** page of the QwenPaw Ollama provider and click **Discover Models** to get the list of available Ollama models. After fetching, you can further click **Test Connection** to verify if the models are working properly.

![Ollama Model List](https://img.alicdn.com/imgextra/i1/O1CN01BbAw7o1W7QkXG8C8k_!!6000000002741-2-tps-1290-1504.png)

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

3. Go back to the QwenPaw LM Studio provider page and click **Discover Models** to add the model to QwenPaw.

The subsequent process is the same as for Ollama: click **Test Connection** to verify the connection, then go to the LM Studio model management page and click **Discover Models** to get the list of available models. After fetching, you can further click **Test Connection** to verify if the models are working properly.

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

![Cloud Provider List](https://img.alicdn.com/imgextra/i4/O1CN01nXGQLF1zgLozc0v2d_!!6000000006743-2-tps-3810-2064.png)

To activate a cloud provider, go to the provider's configuration page. Most cloud providers have pre-configured base URL; you only need to enter your API Key.

![Configure API Key](https://gw.alicdn.com/imgextra/i4/O1CN01pbLeu81jIVKRoGrSk_!!6000000004525-2-tps-1058-772.png)

After entering the API Key, click the **Test Connection** button. The system will automatically verify whether the API Key is correct (only supported by some providers).

![Test Connection Result](https://gw.alicdn.com/imgextra/i1/O1CN01dGL7cJ1jH88mTpW9z_!!6000000004522-2-tps-1088-946.png)

Once the cloud provider is configured, you can further check if the models are available. A series of models are preset for each cloud provider. You can click the **Test Connection** button for a specific model on the provider's model management page to verify if the model is working properly.

![Model Connection Test Result](https://img.alicdn.com/imgextra/i3/O1CN01tKRARl1UaAMsQC4En_!!6000000002533-2-tps-1268-1508.png)

If the preset models do not meet your needs, you can also click **Add Model** on the model management page to add new models. When adding, you need to provide the **Model ID** (the identifier used by the API, usually found in the provider's documentation) and the **Model Name** (for display in the UI). Manually added models can also be tested using the **Test Connection** button.

![Add Model](https://img.alicdn.com/imgextra/i3/O1CN01gvYta11FXfyhNGE89_!!6000000000497-2-tps-1260-1692.png)

## Custom Provider Configuration

If the preset cloud and local providers do not meet your needs, QwenPaw also supports custom providers.

### Add Provider

You can add a new provider by clicking **Add Provider** in the upper right corner of **Settings -> Models -> Providers**. When adding, you need to provide the **Provider ID** (for internal indexing in QwenPaw) and **Provider Name** (for display in the UI), and select the API compatibility mode (currently supports OpenAI `chat.completions` and Anthropic `messages`). After adding, you can add models under this provider just like with cloud providers, and select the provider's models in chat and other scenarios.

![Add Provider](https://img.alicdn.com/imgextra/i4/O1CN019j9pgB1dzCZmsnMlW_!!6000000003806-2-tps-3810-2064.png)

### Configure Provider

After adding a provider, go to its **Settings** page to configure the API access information, including _Base URL_ and _API Key_.

![Custom Provider Settings](https://img.alicdn.com/imgextra/i2/O1CN01XHC4521TzWgODbUFa_!!6000000002453-2-tps-1180-1204.png)

### Add Model

After configuring a custom provider, go to its **Models** page and click **Add Model**. When adding, you need to provide the **Model ID** (the identifier used by the API) and **Model Name** (for display in the UI). After adding, you can also use **Test Connection** to verify if the model is working properly.

> For example, if you deploy vLLM at `http://localhost:8000` and have a model at `/path/to/Qwen3.5`, you can add a custom provider, set the API compatibility mode to OpenAI `chat.completions`, set the Base URL to `http://localhost:8000/v1`, then add a model under this provider with Model ID `/path/to/Qwen3.5` and Model Name `Qwen3.5`. After testing the connection, if everything is configured correctly, you can use this vLLM model in QwenPaw.

## Selecting a Model

Configured model providers and models will appear in the **Settings -> Models -> Default LLM** list. You can select a model as the global default and click the **Save** button on the right. The model set on this page will be used as the global default by QwenPaw. If you do not specify a model in certain scenarios (such as chat), QwenPaw will use the default model set here.

![Default Model Settings](https://img.alicdn.com/imgextra/i1/O1CN01bLNFam20DKL1tYThY_!!6000000006815-2-tps-3810-2064.png)

Since different tasks may require different model capabilities, QwenPaw also supports using different models in different chats. You can select the appropriate provider and model from the dropdown menu in the upper right corner of the **Chat** page. This setting only applies to the current agent and chat. If you do not configure a provider or model in the chat page, QwenPaw will use the global default model.

![Chat Model Settings](https://img.alicdn.com/imgextra/i2/O1CN01Vq1yXW1Oy5NHgBLmR_!!6000000001773-2-tps-3810-2064.png)

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

![Generation Parameters](https://img.alicdn.com/imgextra/i1/O1CN0194Bihd239bxJwoVpi_!!6000000007213-2-tps-1180-1858.png)
