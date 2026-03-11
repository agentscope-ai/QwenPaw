# Models

You need to configure a model before chatting with CoPaw. You can do this under **Console → Settings → Models**.

![Console models](https://img.alicdn.com/imgextra/i1/O1CN01zHAE1Z26w6jXl2xbr_!!6000000007725-2-tps-3802-1968.png)

CoPaw supports multiple LLM providers: **cloud providers** (require API Key), **local providers** (llama.cpp / MLX), **Ollama provider**, **LM Studio provider**, and you can add **custom providers**. This page explains how to configure each type.

---

## Configure cloud providers

Cloud providers (including ModelScope, DashScope, Aliyun Coding Plan, OpenAI, and Azure OpenAI) call remote models via API and require an **API Key**.

**In the console:**

1. Open the console and go to **Settings → Models**.
2. Find the target cloud provider card (e.g. DashScope) and click **Settings**. Enter your **API key** and click **Save**.

   ![save](https://img.alicdn.com/imgextra/i1/O1CN01zHAE1Z26w6jXl2xbr_!!6000000007725-2-tps-3802-1968.png)

3. After saving, the card status in the top-right becomes **Available**. In the **LLM Configuration** section at the top, you can select this provider in the **Provider** dropdown and see the list of models in the **Model** dropdown.

   ![choose](https://img.alicdn.com/imgextra/i2/O1CN01aYwWJ31gsjoGdycs5_!!6000000004198-2-tps-3802-1968.png)

4. Choose the target model (e.g. qwen3.5-plus) and click **Save**.

   ![save](https://img.alicdn.com/imgextra/i3/O1CN01oQTx2a1Qey37oM3Tw_!!6000000002002-2-tps-3802-1968.png)

5. The LLM Configuration bar will show the current provider and model in the top-right.

   ![model](https://img.alicdn.com/imgextra/i1/O1CN018wZ0C81MWweGbYL33_!!6000000001443-2-tps-3802-1968.png)

> To revoke a cloud provider, click **Settings** on its card, then **Revoke Authorization** and confirm. The provider status will change to **Unavailable**.
>
> ![cancel](https://img.alicdn.com/imgextra/i2/O1CN01A8j1IR1n8fHGnio0q_!!6000000005045-2-tps-3802-1968.png)

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

6. In **LLM Configuration** at the top, select the local provider in the **Provider** dropdown and the newly added model in the **Model** dropdown, then click **Save**.

   ![model](https://img.alicdn.com/imgextra/i1/O1CN015KoPYh1cCp6H4rkN9_!!6000000003565-2-tps-3802-1968.png)

7. The LLM Configuration area will show the local provider and the selected model name.

   ![see](https://img.alicdn.com/imgextra/i1/O1CN01Dce5Pt1GH1BBxJcjD_!!6000000000596-2-tps-3802-1968.png)

> Click **Models** on a local provider card to see model names, sizes, and sources. To remove a model, click the **trash icon** on the right of that model and confirm.
>
> ![delete](https://img.alicdn.com/imgextra/i4/O1CN01roGD1X1lKudZT51co_!!6000000004801-2-tps-3802-1968.png)

## Ollama provider

The Ollama provider uses the **Ollama daemon** installed on your machine. Models are managed by Ollama; CoPaw does not download them directly, and the list syncs with Ollama.

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

6. When done, in **LLM Configuration** at the top, select **Ollama** in the **Provider** dropdown and your model in the **Model** dropdown, then click **Save**.

   ![save](https://img.alicdn.com/imgextra/i3/O1CN01DEOqAH1ODMx4rUTLw_!!6000000001671-2-tps-3802-1968.png)

7. The LLM Configuration area will show the Ollama provider and the selected model name.

   ![name](https://img.alicdn.com/imgextra/i2/O1CN01955KEG1vtOcDcdedZ_!!6000000006230-2-tps-3802-1968.png)

> If you see `Ollama SDK not installed. Install with: pip install 'copaw[ollama]'`, make sure Ollama is installed from ollama.com and you’ve run `pip install 'copaw[ollama]'` in CoPaw’s environment. To remove a model, click **Models** on the Ollama card, then the **trash icon** next to the model and confirm.
>
> ![delete](https://img.alicdn.com/imgextra/i1/O1CN01OvNNu21shXVzD14go_!!6000000005798-2-tps-3802-1968.png)
>
> **Docker users:** If CoPaw runs inside a Docker container, `localhost` refers to the container — not your host machine. Change the Ollama Base URL to `http://host.docker.internal:11434` (and add `--add-host=host.docker.internal:host-gateway` to your `docker run` command). See the [Docker section in the README](https://github.com/agentscope-ai/CoPaw#using-docker) for details.

## LM Studio provider

The LM Studio provider connects to the **LM Studio** desktop application's built-in OpenAI-compatible server. Models are managed in the LM Studio GUI; CoPaw discovers loaded models automatically via the `/v1/models` endpoint.

**Prerequisites:**

- Install LM Studio from [lmstudio.ai](https://lmstudio.ai).
- In LM Studio, load a model and start the local server (default: `http://localhost:1234`).

1. On the Models page you'll see the LM Studio provider card.

2. Click **Settings** at the bottom right. The default Base URL is `http://localhost:1234/v1`. Adjust if you changed the port in LM Studio. Click **Save**.

3. Click **Models** to view models currently loaded in LM Studio. You can also manually add a model ID if needed.

4. In **LLM Configuration** at the top, select **LM Studio** in the **Provider** dropdown and your model in the **Model** dropdown, then click **Save**.

> **Tip:** LM Studio does not require an API key by default. If you have enabled authentication in LM Studio, enter the key in the **API Key** field. Models must be loaded in LM Studio's GUI before they appear in CoPaw.
>
> **Important — Context Length:** LM Studio loads models with a small default context length (often 2048 or 4096 tokens). CoPaw's system prompt (AGENTS.md + SOUL.md + PROFILE.md) can easily exceed this limit, causing an error like _"The number of tokens to keep from the initial prompt is greater than the context length"_. To fix this, **unload the model in LM Studio and reload it with a larger context length** (16384 or above is recommended). You can do this in the LM Studio GUI (Model Settings → Context Length) or via the CLI: `lms unload --all && lms load <model> -c 16384`.
>
> **Docker users:** If CoPaw runs inside a Docker container, `localhost` refers to the container — not your host machine. Change the LM Studio Base URL to `http://host.docker.internal:1234/v1` (and add `--add-host=host.docker.internal:host-gateway` to your `docker run` command). See the [Docker section in the README](https://github.com/agentscope-ai/CoPaw#using-docker) for details.

## Add custom provider

1. On the Models page click **Add provider**.

   ![add](https://img.alicdn.com/imgextra/i2/O1CN018PFJmz1kUhUBwf4OL_!!6000000004687-2-tps-3802-1968.png)

2. Enter **Provider ID** and **Display name**, then click **Create**.

   ![create](https://img.alicdn.com/imgextra/i3/O1CN01XuLvkT1wRHvNLHUaf_!!6000000006304-2-tps-3802-1968.png)

3. The new provider card will appear.

   ![card](https://img.alicdn.com/imgextra/i3/O1CN01BFghrw1ZFcfpyzIL7_!!6000000003165-2-tps-3802-1968.png)

4. Click **Settings**, enter **Base URL** and **API Key**, then click **Save**.

   ![save](https://img.alicdn.com/imgextra/i4/O1CN01R5ZTQ321ymyQ8psEY_!!6000000007054-2-tps-3802-1968.png)

5. The card will show the configured Base URL and API Key, but the status will still be **Unavailable** until you add a model.

   ![model](https://img.alicdn.com/imgextra/i4/O1CN01qDDA1I1xd1gu7D8w2_!!6000000006465-2-tps-3802-1968.png)

6. Click **Models**, enter the **Model ID**, then click **Add model**.

   ![add](https://img.alicdn.com/imgextra/i2/O1CN01nG1FoA1KyJ4vcUYwo_!!6000000001232-2-tps-3802-1968.png)

7. The custom provider will then show as **Available**. In **LLM Configuration** at the top, select it in the **Provider** dropdown and the new model in the **Model** dropdown, then click **Save**.

   ![model](https://img.alicdn.com/imgextra/i2/O1CN01EtQCWr1YpW63ox5QY_!!6000000003108-2-tps-3802-1968.png)

8. The LLM Configuration area will show the custom provider ID and the selected model name.

   ![save](https://img.alicdn.com/imgextra/i2/O1CN01WPMjKq1bCzdC8RJvP_!!6000000003430-2-tps-3802-1968.png)

> If configuration fails, double-check **Base URL**, **API Key**, and **Model ID** (including case). To remove a custom provider, click **Delete provider** on its card and confirm.
>
> ![delete](https://img.alicdn.com/imgextra/i3/O1CN0124kc9J1dv4zHYDWQg_!!6000000003797-2-tps-3802-1968.png)
