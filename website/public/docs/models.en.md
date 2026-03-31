# Models

Before using CoPaw, you need to configure at least one available model. CoPaw supports multiple model providers, which you can configure and manage on the **Settings -> Models** page in the left sidebar.

![Settings Models](https://gw.alicdn.com/imgextra/i3/O1CN01MmM8iv1rcfh95wdn3_!!6000000005652-2-tps-3394-1880.png)

## Provider Configuration

CoPaw supports various LLM providers:

- **Local Providers** (llama.cpp / Ollama / LM Studio)
- **Cloud Providers** (usually require an API Key)
- **Custom Providers** (if the preset local and cloud providers do not meet your needs)

### Local Provider Configuration

Currently supported local providers include:

- [CoPaw Local (llama.cpp)](https://github.com/ggml-org/llama.cpp)
- [Ollama](https://ollama.com/)
- [LM Studio](https://lmstudio.ai/)

CoPaw Local (llama.cpp) is built into CoPaw and does not require additional software installation. Ollama and LM Studio require you to install the corresponding software in advance.

CoPaw also provides the CoPaw-Flash series for local deployment. It includes 2B, 4B, and 9B variants, with original, 4-bit, and 8-bit versions for different VRAM and performance requirements. These models are open-sourced on [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) and [Hugging Face](https://huggingface.co/agentscope-ai/models). The following sections explain how to use CoPaw-Flash with each local provider.

**CoPaw Local (llama.cpp) Configuration**

CoPaw Local is a local model provider based on llama.cpp. You can configure and manage it on the **Models** page.

> CoPaw Local is currently in the beta phase. There may be stability and compatibility issues on different devices. For a more stable local model experience, it is recommended to use Ollama or LM Studio in the short term.

![CoPaw Local Provider](https://gw.alicdn.com/imgextra/i4/O1CN01OAi8oN1acoLWlsm6B_!!6000000003351-2-tps-2410-1634.png)

When configuring CoPaw Local for the first time, you need to download the llama.cpp runtime. Click the **Download llama.cpp** button, and CoPaw will automatically download and configure the runtime. Once the download is complete, you can use the CoPaw Local provider.

![Download llama.cpp](https://gw.alicdn.com/imgextra/i3/O1CN01Nqs9Cg1Vp6uA2WdiM_!!6000000002701-2-tps-1270-874.png)

CoPaw team has trained a series of small models (the CoPaw-Flash series) suitable for local deployment. Based on your current device (CPU / NVIDIA GPU / Apple M series chip), CoPaw will automatically recommend suitable model versions for you. If you want to use CoPaw-Flash, simply choose an appropriate version here, download it, and start it. If you want to use other models, you can add them by entering the _Model Repository ID_ and _Download Source_. The Model Repository ID refers to the identifier of the model in ModelScope / Hugging Face, such as `Qwen/Qwen3-0.6B-GGUF`. The Download Source refers to where the model is downloaded from. Currently, ModelScope and Hugging Face are supported.

![Download Model](https://gw.alicdn.com/imgextra/i2/O1CN01IF2OXz1c99w9W8XGU_!!6000000003557-2-tps-1226-1202.png)

After the model is downloaded, you can click the **Start** button to launch the model. The startup time may vary depending on the model size. Once started, CoPaw will automatically set this model as the global default. Only one model can be running at a time; starting another model will automatically stop the currently running one.

![Start Model](https://gw.alicdn.com/imgextra/i1/O1CN01NSNFUN1I21RynZwGy_!!6000000000834-2-tps-1224-1194.png)

When you do not need to use a model temporarily, you can click **Stop** to stop the model service.

![Stop Model](https://gw.alicdn.com/imgextra/i4/O1CN01ewNXXD1nMrYq8zvuC_!!6000000005076-2-tps-1230-1284.png)

CoPaw Local will automatically record the model's running state. If you close the CoPaw process while a CoPaw Local model is running, it will attempt to restart the last used model the next time you open CoPaw, so you do not need to start the model manually each time.

**Ollama Configuration**

Before using Ollama, you need to [install Ollama](https://ollama.com/download) on your machine, download at least one model, and set the Context Length to at least 32k on the settings page.

![Ollama Settings](https://gw.alicdn.com/imgextra/i4/O1CN01pWWxlV1QiApLwDzbU_!!6000000002009-2-tps-1912-1510.png)

To verify that Ollama is working properly, go to the **Settings** page of the CoPaw Ollama provider and click the **Test Connection** button.

> For users deploying CoPaw in a Docker container, if Ollama is installed on the host machine, ensure that the Docker network configuration allows the container to access the host's Ollama service (add `--add-host=host.docker.internal:host-gateway` to the `docker run` command), and set the API address to `http://host.docker.internal:11434`.

If you want to use CoPaw-Flash with Ollama, it is recommended to choose a `Q8_0` or `Q4_K_M` quantized variant and import it with the following steps:

1. Download a suitable quantized CoPaw-Flash model from [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) or [Hugging Face](https://huggingface.co/agentscope-ai/models), for example `AgentScope/CoPaw-Flash-4B-Q4_K_M`.

ModelScope CLI:

```bash
modelscope download --model AgentScope/CoPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

Hugging Face CLI:

```bash
hf download agentscope-ai/CoPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

2. Create a text file named `copaw-flash.txt` and replace `/path/to/your/copaw-xxx.gguf` with the absolute path of the downloaded `.gguf` file:

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

3. Run the following command in your terminal to import the model into Ollama:

```bash
ollama create copaw-flash -f copaw-flash.txt
```

4. Go back to the CoPaw Ollama provider page and click **Discover Models** to add the model to CoPaw.

After installing and configuring Ollama, go to the **Models** page of the CoPaw Ollama provider and click **Discover Models** to get the list of available Ollama models. After fetching, you can further click **Test Connection** to verify if the models are working properly.

![Ollama Model List](https://gw.alicdn.com/imgextra/i3/O1CN01esQyTg1eSyIlpRK69_!!6000000003871-2-tps-1208-1322.png)

**LM Studio Configuration**

Before using LM Studio, you need to [install LM Studio](https://lmstudio.ai/download) on your machine.

By default, LM Studio does not enable the model API service. After installing LM Studio and downloading models, go to **Developer -> Local Server** to start the local model service and note the API address, which defaults to `http://localhost:1234`.

![LM Studio Local Server](https://gw.alicdn.com/imgextra/i3/O1CN01kLXu3D1VwRF3lokZz_!!6000000002717-2-tps-1654-1256.png)

To ensure a good experience in CoPaw, set the **Default Context Length** to at least 32768 in **Settings -> Model Defaults**, and enable "When applicable, separate `reasoning_content` and `content` in API responses" in **Settings -> Developer -> Experimental Settings**.

![LM Studio Context Length](https://gw.alicdn.com/imgextra/i4/O1CN011jc2q71hc51etcf7x_!!6000000004297-2-tps-1654-1256.png)

![LM Studio Reasoning Content](https://gw.alicdn.com/imgextra/i4/O1CN01dInPGl1oDX6nOH0Wh_!!6000000005191-2-tps-1654-1256.png)

After completing the above LM Studio configuration, go to the **Settings** page of the CoPaw LM Studio provider and enter the LM Studio API address, which can be found on the **Developer -> Local Server** page. Be sure to add the `/v1` suffix, e.g., `http://localhost:1234/v1`.

If you want to use CoPaw-Flash with LM Studio, it is also recommended to choose a `Q8_0` or `Q4_K_M` quantized variant and import it with the following steps:

1. Download a suitable quantized CoPaw-Flash model from [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) or [Hugging Face](https://huggingface.co/agentscope-ai/models), for example `AgentScope/CoPaw-Flash-4B-Q4_K_M`.

ModelScope CLI:

```bash
modelscope download --model AgentScope/CoPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

Hugging Face CLI:

```bash
hf download agentscope-ai/CoPaw-Flash-4B-Q4_K_M --local_dir ./dir
```

2. Run the following command to import the downloaded `.gguf` file into LM Studio:

```bash
lms import /path/to/your/copaw-xxx.gguf -c -y --user-repo AgentScope/CoPaw-Flash
```

3. Go back to the CoPaw LM Studio provider page and click **Discover Models** to add the model to CoPaw.

The subsequent process is the same as for Ollama: click **Test Connection** to verify the connection, then go to the LM Studio model management page and click **Discover Models** to get the list of available models. After fetching, you can further click **Test Connection** to verify if the models are working properly.

> For users deploying CoPaw in a Docker container, if LM Studio is installed on the host machine, ensure that the Docker network configuration allows the container to access the host's LM Studio service (add `--add-host=host.docker.internal:host-gateway` to the `docker run` command), and set the API address to `http://host.docker.internal:1234/v1`.

### Cloud Provider Configuration

Currently supported cloud providers include:

- ModelScope
- DashScope
- Aliyun Coding Plan
- OpenAI
- Azure OpenAI
- Anthropic
- Google Gemini
- MiniMax

> Some providers offer different base URLs for Mainland China and other regions. Please select the correct provider based on your location.

![Cloud Provider List](https://gw.alicdn.com/imgextra/i3/O1CN01EoK2LV2AH7lFM4GJu_!!6000000008177-2-tps-3402-1942.png)

To activate a cloud provider, go to the provider's configuration page. Most cloud providers have pre-configured base URL; you only need to enter your API Key.

![Configure API Key](https://gw.alicdn.com/imgextra/i4/O1CN01pbLeu81jIVKRoGrSk_!!6000000004525-2-tps-1058-772.png)

After entering the API Key, click the **Test Connection** button. The system will automatically verify whether the API Key is correct (only supported by some providers).

![Test Connection Result](https://gw.alicdn.com/imgextra/i1/O1CN01dGL7cJ1jH88mTpW9z_!!6000000004522-2-tps-1088-946.png)

Once the cloud provider is configured, you can further check if the models are available. A series of models are preset for each cloud provider. You can click the **Test Connection** button for a specific model on the provider's model management page to verify if the model is working properly.

![Model Connection Test Result](https://gw.alicdn.com/imgextra/i3/O1CN01aAyd2L1N77wX0OvtY_!!6000000001522-2-tps-1150-1154.png)

If the preset models do not meet your needs, you can also click **Add Model** on the model management page to add new models. When adding, you need to provide the **Model ID** (the identifier used by the API, usually found in the provider's documentation) and the **Model Name** (for display in the UI). Manually added models can also be tested using the **Test Connection** button.

![Add Model](https://gw.alicdn.com/imgextra/i1/O1CN01FBIdEH1ud4tTIHpEZ_!!6000000006059-2-tps-1148-1342.png)

### Custom Provider Configuration

If the preset cloud and local providers do not meet your needs, CoPaw also supports custom providers.

#### Add Provider

You can add a new provider by clicking **Add Provider** in the upper right corner of **Settings -> Models -> Providers**. When adding, you need to provide the **Provider ID** (for internal indexing in CoPaw) and **Provider Name** (for display in the UI), and select the API compatibility mode (currently supports OpenAI `chat.completions` and Anthropic `messages`). After adding, you can add models under this provider just like with cloud providers, and select the provider's models in chat and other scenarios.

![Add Provider](https://gw.alicdn.com/imgextra/i1/O1CN01UE3Vbu1hGYPWlzpps_!!6000000004250-2-tps-3394-1882.png)

#### Configure Provider

After adding a provider, go to its **Settings** page to configure the API access information, including _Base URL_ and _API Key_.

![Custom Provider Settings](https://gw.alicdn.com/imgextra/i1/O1CN01naWZLN1T8OjjlOtWo_!!6000000002337-2-tps-1118-1172.png)

#### Add Model

After configuring a custom provider, go to its **Models** page and click **Add Model**. When adding, you need to provide the **Model ID** (the identifier used by the API) and **Model Name** (for display in the UI). After adding, you can also use **Test Connection** to verify if the model is working properly.

> For example, if you deploy vLLM at `http://localhost:8000` and have a model at `/path/to/Qwen3.5`, you can add a custom provider, set the API compatibility mode to OpenAI `chat.completions`, set the Base URL to `http://localhost:8000/v1`, then add a model under this provider with Model ID `/path/to/Qwen3.5` and Model Name `Qwen3.5`. After testing the connection, if everything is configured correctly, you can use this vLLM model in CoPaw.

## Selecting a Model

Configured model providers and models will appear in the **Settings -> Models -> Default LLM** list. You can select a model as the global default and click the **Save** button on the right. The model set on this page will be used as the global default by CoPaw. If you do not specify a model in certain scenarios (such as chat), CoPaw will use the default model set here.

![Default Model Settings](https://gw.alicdn.com/imgextra/i4/O1CN01NH2eBZ1UBQyhucWdj_!!6000000002479-2-tps-3388-808.png)

Since different tasks may require different model capabilities, CoPaw also supports using different models in different chats. You can select the appropriate provider and model from the dropdown menu in the upper right corner of the **Chat** page. This setting only applies to the current agent and chat. If you do not configure a provider or model in the chat page, CoPaw will use the global default model.

![Chat Model Settings](https://gw.alicdn.com/imgextra/i3/O1CN01BjQlqH1eC1eC7xNm8_!!6000000003834-2-tps-3402-1768.png)

## Advanced Model Configuration

### Model Configuration Files

All provider configurations in CoPaw are saved in the `$COPAW_SECRET_DIR/providers` folder (default `~/.copaw.secret/providers`). Built-in provider configurations are in the `builtin` directory, and user-added custom provider configurations are in the `custom` directory. Each provider has a corresponding JSON file named after its ID, e.g., the configuration file for a provider with ID `Qwen` is `Qwen.json`. The file contains the provider's API access information and model list. It is not recommended for regular users to modify these files directly to avoid unnecessary errors. Also, changes to the configuration files require restarting CoPaw to take effect.

### Local Models

If you use the CoPaw Local (llama.cpp) provider, CoPaw will save the llama.cpp runtime and model files in the `$COPAW_WORKING_DIR/local_models` folder (default `~/.copaw/local_models`). The runtime is saved in the `$COPAW_WORKING_DIR/local_models/bin` directory, and downloaded models are saved in the `$COPAW_WORKING_DIR/local_models/models` directory. Each model has a corresponding folder named after its ID, e.g., the folder for the model ID `Qwen/Qwen3-0.6B-GGUF` is `$COPAW_WORKING_DIR/local_models/models/Qwen/Qwen3-0.6B-GGUF`. The model folder contains the GGUF file and some model metadata files.

If you need more advanced usage of llama.cpp (such as using hardware-specific acceleration), you can compile your own version of llama.cpp and replace the `llama-server` file in the `bin` directory.

If you want to use GGUF model files from other sources, you can create a subfolder with the structure `organization/model_name` under the `models` directory, then save the `GGUF` file in that folder. After refreshing the CoPaw Local model list, you will see the model in the list (e.g., save `Qwen3-0.6B.gguf` to `$COPAW_WORKING_DIR/local_models/models/Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B.gguf`).

### Generation Parameters

Since different models and tasks may require different generation parameters (such as `temperature`, `top_p`, `max_tokens`), CoPaw supports configuring generation parameters in the provider settings. Go to the provider's **Settings** page, expand **Advanced Configuration**, and enter the parameter configuration in JSON format, for example:

```json
{
  "temperature": 0.7,
  "top_p": 0.9,
  "max_tokens": 4096
}
```

After configuring, click **Save**. CoPaw will automatically include these parameters when generating with models from this provider.

![Generation Parameters](https://gw.alicdn.com/imgextra/i2/O1CN01et3R371uamugLZiT0_!!6000000006054-2-tps-1078-1732.png)
