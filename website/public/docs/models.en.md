# Models

Before using CoPaw, you need to configure at least one available model. CoPaw supports multiple model providers, which you can configure and manage on the **Settings -> Models** page in the left sidebar.

![Console Models]()

## Provider Configuration

CoPaw supports various LLM providers:

- **Cloud Providers** (usually require an API Key)
- **Local Providers** (llama.cpp / Ollama / LMStudio)
- **Custom Providers** (if the preset cloud and local providers do not meet your needs)

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

![Cloud Provider List]()

To activate a cloud provider, go to the provider's configuration page. Most cloud providers have pre-configured base URL; you only need to enter your API Key.

![Configure API Key]()

After entering the API Key, click the **Test Connection** button. The system will automatically verify whether the API Key is correct (only supported by some providers).

![Test Connection Result]()

Once the cloud provider is configured, you can further check if the models are available. A series of models are preset for each cloud provider. You can click the **Test Connection** button for a specific model on the provider's model management page to verify if the model is working properly.

![Model Connection Test Result]()

If the preset models do not meet your needs, you can also click **Add Model** on the model management page to add new models. When adding, you need to provide the **Model ID** (the identifier used by the API, usually found in the provider's documentation) and the **Model Name** (for display in the UI). Manually added models can also be tested using the **Test Connection** button.

![Add Model]()

### Local Provider Configuration

Currently supported local providers include:

- [CoPaw Local (llama.cpp)](https://github.com/ggml-org/llama.cpp)
- [Ollama](https://ollama.com/)
- [LM Studio](https://lmstudio.ai/)

CoPaw Local (llama.cpp) is built into CoPaw and does not require additional software installation. Ollama and LM Studio require you to install the corresponding software in advance.

#### CoPaw Local (llama.cpp) Configuration

CoPaw Local is a local model provider based on llama.cpp. You can configure and manage it on the **Models** page.

> CoPaw Local is currently in the beta phase. There may be stability and compatibility issues on different devices. For a more stable local model experience, it is recommended to use Ollama or LM Studio in the short term.

![CoPaw Local Provider]()

When configuring CoPaw Local for the first time, you need to download the llama.cpp runtime. Click the **Download llama.cpp** button, and CoPaw will automatically download and configure the runtime. Once the download is complete, you can use the CoPaw Local provider.

![Download llama.cpp]()

After downloading llama.cpp, the page will display a list of recommended models based on your machine. You can select the models you need to download. If you want to use other models, you can add them by entering the *Model Repository ID* and *Download Source*. The Model Repository ID refers to the identifier of the model in ModelScope / Hugging Face, such as `Qwen/Qwen3-0.6B-GGUF`. The Download Source refers to the source for downloading the model. Currently, ModelScope and Hugging Face are supported.

![Download Model]()

After the model is downloaded, you can click the **Start** button to launch the model. The startup time may vary depending on the model size. Once started, CoPaw will automatically set this model as the global default. Only one model can be running at a time; starting another model will automatically stop the currently running one.

![Start Model]()

When you do not need to use a model temporarily, you can click **Stop** to stop the model service.

![Stop Model]()

CoPaw Local will automatically record the model's running state. If you close the CoPaw process while a CoPaw Local model is running, it will attempt to restart the last used model the next time you open CoPaw, so you do not need to start the model manually each time.

#### Ollama Configuration

Before using Ollama, you need to [install Ollama](https://ollama.com/download) on your machine, download at least one model, and set the Context Length to at least 32k on the settings page.

![Ollama Settings]()

To verify that Ollama is working properly, go to the **Settings** page of the CoPaw Ollama provider and click the **Test Connection** button.

> For users deploying CoPaw in a Docker container, if Ollama is installed on the host machine, ensure that the Docker network configuration allows the container to access the host's Ollama service (add `--add-host=host.docker.internal:host-gateway` to the `docker run` command), and set the API address to `http://host.docker.internal:11434`.

After installing and configuring Ollama, go to the **Models** page of the CoPaw Ollama provider and click **Auto Fetch Models** to get the list of available Ollama models. After fetching, you can further click **Test Connection** to verify if the models are working properly.

![Ollama Model List]()

#### LM Studio Configuration

Before using LM Studio, you need to [install LM Studio](https://lmstudio.ai/download) on your machine.

By default, LM Studio does not enable the model API service. After installing LM Studio and downloading models, go to **Developer -> Local Server** to start the local model service and note the API address, which defaults to `https://localhost:1234`.

![LM Studio Local Server]()

To ensure a good experience in CoPaw, set the **Default Context Length** to at least 32768 in **Settings -> Model Defaults**, and enable "When applicable, separate `reasoning_content` and `content` in API responses" in **Settings -> Developer -> Experimental Settings**.

![LM Studio Context Length]()

![LM Studio Reasoning Content]()

After completing the above LM Studio configuration, go to the **Settings** page of the CoPaw LM Studio provider and enter the LM Studio API address, which can be found on the **Developer -> Local Server** page. Be sure to add the `/v1` suffix, e.g., `https://localhost:1234/v1`.

The subsequent process is the same as for Ollama: click **Test Connection** to verify the connection, then go to the LM Studio model management page and click **Auto Fetch Models** to get the list of available models. After fetching, you can further click **Test Connection** to verify if the models are working properly.

> For users deploying CoPaw in a Docker container, if LM Studio is installed on the host machine, ensure that the Docker network configuration allows the container to access the host's LM Studio service (add `--add-host=host.docker.internal:host-gateway` to the `docker run` command), and set the API address to `https://host.docker.internal:1234/v1`.

### Custom Provider Configuration

If the preset cloud and local providers do not meet your needs, CoPaw also supports custom providers.

#### Add Provider

You can add a new provider by clicking **Add Provider** in the upper right corner of **Settings -> Models -> Providers**. When adding, you need to provide the **Provider ID** (for internal indexing in CoPaw) and **Provider Name** (for display in the UI), and select the API compatibility mode (currently supports OpenAI `chat.completions` and Anthropic `messages`). After adding, you can add models under this provider just like with cloud providers, and select the provider's models in chat and other scenarios.

![Add Provider]()

#### Configure Provider

After adding a provider, go to its **Settings** page to configure the API access information, including *Base URL* and *API Key*.

![Custom Provider Settings]()

#### Add Model

After configuring a custom provider, go to its **Models** page and click **Add Model**. When adding, you need to provide the **Model ID** (the identifier used by the API) and **Model Name** (for display in the UI). After adding, you can also use **Test Connection** to verify if the model is working properly.

> For example, if you deploy vLLM at `http://localhost:8000` and have a model at `/path/to/Qwen3.5`, you can add a custom provider, set the API compatibility mode to OpenAI `chat.completions`, set the Base URL to `http://localhost:8000/v1`, then add a model under this provider with Model ID `/path/to/Qwen3.5` and Model Name `Qwen3.5`. After testing the connection, if everything is configured correctly, you can use this vLLM model in CoPaw.

## Selecting a Model

Configured model providers and models will appear in the **Settings -> Models -> Default LLM** list. You can select a model as the global default and click the **Save** button on the right. The model set on this page will be used as the global default by CoPaw. If you do not specify a model in certain scenarios (such as chat), CoPaw will use the default model set here.

![Default Model Settings]()

Since different tasks may require different model capabilities, CoPaw also supports using different models in different chats. You can select the appropriate provider and model from the dropdown menu in the upper right corner of the **Chat** page. This setting only applies to the current agent and chat. If you do not configure a provider or model in the chat page, CoPaw will use the global default model.

![Chat Model Settings]()

## Advanced Model Configuration

### Model Configuration Files

All provider configurations in CoPaw are saved in the `$COPAW_SECRET_DIR/providers` folder (default `~/.copaw.secret/providers`). Built-in provider configurations are in the `builtin` directory, and user-added custom provider configurations are in the `custom` directory. Each provider has a corresponding JSON file named after its ID, e.g., the configuration file for a provider with ID `Qwen` is `Qwen.json`. The file contains the provider's API access information and model list. It is not recommended for regular users to modify these files directly to avoid unnecessary errors. Also, changes to the configuration files require restarting CoPaw to take effect.

### Local Models

If you use the CoPaw Local (llama.cpp) provider, CoPaw will save the llama.cpp runtime and model files in the `$COPAW_WORKING_DIR/local_models` folder (default `~/.copaw/local_models`). The runtime is saved in the `bin` directory, and downloaded models are saved in the `models` directory. Each model has a corresponding folder named after its ID, e.g., the folder for the model ID `Qwen/Qwen3-0.6B-GGUF` is `Qwen/Qwen3-0.6B-GGUF`. The model folder contains the GGUF file and some model metadata files.

If you need more advanced usage of llama.cpp (such as using hardware-specific acceleration), you can compile your own version of llama.cpp and replace the `llama-server` file in the `bin` directory.

If you want to use GGUF model files from other sources, you can create a subfolder with the structure `organization/model_name` under the `models` directory, then save the `GGUF` file in that folder. After refreshing the CoPaw Local model list, you will see the model in the list (e.g., save `Qwen3-0.6B.gguf` to `models/Qwen/Qwen3-0.6B-GGUF/Qwen3-0.6B.gguf`).

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

![Generation Parameters]()
