# Models

You need to configure a model before chatting with CoPaw. Use **Console → Settings → Models** for the quickest setup.

After configuration, choose **Default LLM** at the top of the Models page. New agents use that global default. To override, open **Chat** and pick a model in the top-left for the current agent.

![Console models](https://img.alicdn.com/imgextra/i1/O1CN01zHAE1Z26w6jXl2xbr_!!6000000007725-2-tps-3802-1968.png)

CoPaw supports multiple LLM providers: **cloud providers** (require an API Key, including Google Gemini), **local providers** (llama.cpp / MLX), **Ollama**, **LM Studio**, and **custom providers**. This page explains how to configure each.

---

## Configure cloud providers

Cloud providers (including ModelScope, DashScope, Aliyun Coding Plan, OpenAI, Azure OpenAI, Google Gemini, and MiniMax) call remote models via API and require an **API Key**.

**In the console:**

1. Open the console and go to **Settings → Models**.
2. Find the target cloud provider card (e.g. DashScope) and click **Settings**. Enter your **API key** and click **Save**.

   ![save](https://img.alicdn.com/imgextra/i3/O1CN01oQTx2a1Qey37oM3Tw_!!6000000002002-2-tps-3802-1968.png)

3. After saving, under **Default LLM** at the top of the Models page, select the provider and model, then **Save** to set the global default.

4. To use a different model per agent, switch the agent with the selector at the top of the console, then choose a model in the top-left of **Chat** for that agent.

> To revoke a cloud provider, open **Settings** on its card → **Revoke authorization** and confirm. The provider becomes **unavailable**.
>
> ![cancel](https://img.alicdn.com/imgextra/i2/O1CN01A8j1IR1n8fHGnio0q_!!6000000005045-2-tps-3802-1968.png)

## Google Gemini provider

The Google Gemini provider uses Google's native Gemini API (via the `google-genai` SDK) to access Gemini models. Pre-configured models include Gemini 3.1 Pro Preview, Gemini 3 Flash Preview, Gemini 3.1 Flash Lite Preview, Gemini 2.5 Pro, Gemini 2.5 Flash, Gemini 2.5 Flash Lite, and Gemini 2.0 Flash. Additional models can be auto-discovered from the API.

**Prerequisites:**

- Obtain a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).

**In the console:**

1. Open the console and go to **Settings → Models**.
2. Find the **Google Gemini** card and click **Settings**. Enter your **API Key** and **Save**.
3. After saving, the card shows **Available**. The provider supports **model discovery** — click **Models** to discover Gemini models from the API.
4. Under **Default LLM**, set **Provider** to **Google Gemini**, pick a model (e.g. `gemini-2.5-flash`), and **Save** for the global default.
5. For a per-agent model, switch agent at the top of the console, then pick a model in the top-left of **Chat**.

**Using the CLI:**

```bash
# Configure the API key
copaw models config-key gemini

# Set Gemini as the active LLM
copaw models set-llm
```

> **Tip:** Gemini models with thinking capabilities (e.g. Gemini 3.1 Pro, Gemini 2.5 Pro, Gemini 2.5 Flash) support extended reasoning. CoPaw automatically handles thinking blocks and thought signatures from these models.

## Local providers (llama.cpp / MLX)

Local providers run models on your machine with **no API Key**; data stays on-device.

**Prerequisites:**

- Install the matching backend in the same environment as CoPaw:
  - llama.cpp: `pip install 'copaw[llamacpp]'`
  - MLX: `pip install 'copaw[mlx]'`

1. On the Models page you’ll see cards for llama.cpp and MLX.

   ![card](https://img.alicdn.com/imgextra/i3/O1CN01Xpbl8a1nJemcFr97p_!!6000000005069-2-tps-3802-1968.png)

2. Click **Models** on the target local provider card (e.g. llama.cpp), then **Download model**.

   ![download](https://img.alicdn.com/imgextra/i3/O1CN01ML9Ce81kyvcoD92hG_!!6000000004753-2-tps-3802-1968.png)

3. Enter the **Repo ID** and choose the **Source**, then click **Download model**.

   ![id](https://img.alicdn.com/imgextra/i3/O1CN01HaIQwC1qV3UHvsvgc_!!6000000005500-2-tps-3802-1968.png)

4. The download will run; wait for it to finish.

   ![wait](https://img.alicdn.com/imgextra/i2/O1CN018b8woI1yHmwOJB2V6_!!6000000006554-2-tps-3802-1968.png)

5. When the download completes, the local provider card status becomes **Available**.

   ![avai](https://img.alicdn.com/imgextra/i4/O1CN01yazvrI25tWt9WqD8w_!!6000000007584-2-tps-3802-1968.png)

6. Under **Default LLM**, select the local provider and a downloaded model, then **Save** for the global default.

7. For a per-agent model, switch agent at the top of the console, then pick a model in **Chat**.

> Open **Models** on a local card to see names, sizes, and sources. To delete, click the **trash** icon on a row and confirm.
>
> ![delete](https://img.alicdn.com/imgextra/i4/O1CN01roGD1X1lKudZT51co_!!6000000004801-2-tps-3802-1968.png)

## Ollama provider

The Ollama provider uses the **Ollama daemon** on your machine. CoPaw does not download model files itself; the list stays in sync with Ollama.

**Prerequisites:**

- Install Ollama from [ollama.com](https://ollama.com).
- Install Ollama support in CoPaw’s environment: `pip install 'copaw[ollama]'`.

1. On the Models page you’ll see the Ollama provider card.

2. Click **Settings** at the bottom right. On the Ollama config page, enter an **API Key** (any value is fine, e.g. `ollama`). Click **Save**.

   ![set](https://img.alicdn.com/imgextra/i1/O1CN01JhGTpy1FPQqDXSVo9_!!6000000000479-2-tps-3802-1968.png)

3. Click **Models** at the bottom right. If you’ve already pulled models with Ollama, they’ll appear here. To pull a new model, click **Download model**.

   ![download](https://img.alicdn.com/imgextra/i2/O1CN01CARKar1ilzCd0dIZ9_!!6000000004454-2-tps-3802-1968.png)

4. Enter the **Model name**, then click **Download Model**.

   ![download](https://img.alicdn.com/imgextra/i3/O1CN014JJgSv24of3xUkGch_!!6000000007438-2-tps-3802-1968.png)

5. The model will download; wait for it to complete.

   ![wait](https://img.alicdn.com/imgextra/i3/O1CN01ptZICs25rEuMA4O7U_!!6000000007579-2-tps-3802-1968.png)

6. Under **Default LLM**, choose Ollama and your model, then **Save** for the global default.

7. For a per-agent model, switch agent at the top, then pick a model in **Chat**.

> If you see `Ollama SDK not installed. Install with: pip install 'copaw[ollama]'`, install Ollama from ollama.com and run `pip install 'copaw[ollama]'` in CoPaw’s environment. To remove a model, open **Models** on the Ollama card and use the **trash** button, then confirm.
>
> **Docker users:** Inside a container, `localhost` is the container, not the host. Set Ollama Base URL to `http://host.docker.internal:11434` and add `--add-host=host.docker.internal:host-gateway` to `docker run`. See the [README Docker section](https://github.com/agentscope-ai/CoPaw#using-docker).
>
> ![delete](https://img.alicdn.com/imgextra/i1/O1CN01OvNNu21shXVzD14go_!!6000000005798-2-tps-3802-1968.png)

## LM Studio provider

The LM Studio provider connects to the **LM Studio** app’s OpenAI-compatible server. Models are managed in LM Studio; CoPaw discovers them via `/v1/models`.

**Prerequisites:**

- Install LM Studio from [lmstudio.ai](https://lmstudio.ai).
- In LM Studio, load a model and start the local server (default: `http://localhost:1234`).

1. On the Models page you'll see the LM Studio provider card.

2. Click **Settings** at the bottom right. The default Base URL is `http://localhost:1234/v1`. Adjust if you changed the port in LM Studio. Click **Save**.

3. Click **Models** to view models currently loaded in LM Studio. You can also manually add a model ID if needed.

4. Under **Default LLM**, pick LM Studio and a model, then **Save** for the global default.

5. For a per-agent model, switch agent at the top, then pick a model in **Chat**.

> **Tip:** LM Studio usually needs no API key. If you enabled auth in LM Studio, fill **API Key** here. Models must be loaded in LM Studio before they show in CoPaw.
>
> **Important — context length:** LM Studio defaults are often 2048–4096 tokens. CoPaw’s system prompt (AGENTS.md + SOUL.md + PROFILE.md) can exceed that and trigger _"The number of tokens to keep from the initial prompt is greater than the context length"_. **Unload the model in LM Studio and reload with a larger context** (≥ 16384 recommended), e.g. in the GUI (Model settings → Context length) or CLI: `lms unload --all && lms load <model> -c 16384`.
>
> **Docker users:** Use `http://host.docker.internal:1234/v1` and `--add-host=host.docker.internal:host-gateway`. See the [README Docker section](https://github.com/agentscope-ai/CoPaw#using-docker).

## Add custom provider

1. On the Models page, click **Add provider**.

   ![add](https://img.alicdn.com/imgextra/i2/O1CN018PFJmz1kUhUBwf4OL_!!6000000004687-2-tps-3802-1968.png)

2. Enter **Provider ID** and **Display name**, then **Create**.

   ![create](https://img.alicdn.com/imgextra/i3/O1CN01XuLvkT1wRHvNLHUaf_!!6000000006304-2-tps-3802-1968.png)

3. The new card appears.

   ![card](https://img.alicdn.com/imgextra/i3/O1CN01BFghrw1ZFcfpyzIL7_!!6000000003165-2-tps-3802-1968.png)

4. Click **Settings**, enter **Base URL** and **API Key**, then **Save**.

   ![save](https://img.alicdn.com/imgextra/i4/O1CN01R5ZTQ321ymyQ8psEY_!!6000000007054-2-tps-3802-1968.png)

5. The card shows Base URL and API Key but stays **Unavailable** until you add a model.

   ![model](https://img.alicdn.com/imgextra/i4/O1CN01qDDA1I1xd1gu7D8w2_!!6000000006465-2-tps-3802-1968.png)

6. Click **Models**, enter **Model ID**, then **Add model**.

   ![add](https://img.alicdn.com/imgextra/i2/O1CN01nG1FoA1KyJ4vcUYwo_!!6000000001232-2-tps-3802-1968.png)

7. The provider becomes **Available**. Under **Default LLM**, select it and the model, then **Save** for the global default.

8. For a per-agent model, switch agent at the top, then pick a model in **Chat**.

> If setup fails, verify **Base URL**, **API Key**, and **Model ID** (case-sensitive). To remove a custom provider, click **Delete provider** on the card and confirm.
>
> ![delete](https://img.alicdn.com/imgextra/i3/O1CN0124kc9J1dv4zHYDWQg_!!6000000003797-2-tps-3802-1968.png)
