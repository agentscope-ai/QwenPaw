# 模型

在于CoPaw对话前，需要先配置模型。在 **控制台 → 设置 → 模型** 中可以快捷配置。

![控制台模型](https://img.alicdn.com/imgextra/i4/O1CN01XnOPPQ1c99vox3I88_!!6000000003557-2-tps-3786-1980.png)

CoPaw 支持多种 LLM 提供商：**云提供商**（需 API Key，包括 Google Gemini）、**本地提供商**（llama.cpp / MLX）、**Ollama 提供商**、**LM Studio 提供商**，且支持添加自定义 **提供商**。本文介绍这几类提供商的配置方式。

---

## 配置云提供商

云提供商（包括 ModelScope、DashScope、Aliyun Coding Plan、OpenAI、Azure OpenAI、Google Gemini 和 MiniMax）通过 API 调用远程模型，需要配置 **API Key**。

**在控制台中配置：**

1. 打开控制台，进入 **设置 → 模型**。
2. 找到目标云提供商卡片（以 DashScope 为例），点击 **设置**。输入你的 **API key**，点击 **保存**。

   ![save](https://img.alicdn.com/imgextra/i3/O1CN01kra0SI1dnIFofzrfY_!!6000000003780-2-tps-3786-1980.png)

3. 保存后可以看到目标云提供商卡片右上角状态变成 **可用**，此时在上方的 **LLM 配置** 中，**提供商** 对应的下拉菜单中可以选择目标云提供商，**模型** 对应的下拉菜单中出现一系列可选模型。

   ![choose](https://img.alicdn.com/imgextra/i1/O1CN01M88I8s1udzgF9xwy7_!!6000000006061-2-tps-3786-1980.png)

4. 选择目标模型（以 qwen3.5-plus 为例），点击 **保存**。

   ![save](https://img.alicdn.com/imgextra/i3/O1CN019ekcQ629WrkeeEeEI_!!6000000008076-2-tps-3786-1980.png)

5. 可以看到 LLM 配置栏右上角显示当前正在使用的模型提供商及模型。

   ![model](https://img.alicdn.com/imgextra/i4/O1CN01HtvNIK1pcYM6E0A9a_!!6000000005381-2-tps-3786-1980.png)

> 注：如果想撤销某个云提供商授权，点击目标云提供商卡片的 **设置**，点击撤销授权，二次确认撤销授权后，可将目标提供商的状态调整为 **不可用**。
>
> ![cancel](https://img.alicdn.com/imgextra/i2/O1CN01LM3rBG1MejNjEeXs1_!!6000000001460-2-tps-3412-1952.png)

## Google Gemini 提供商

Google Gemini 提供商通过 Google 原生 Gemini API（使用 `google-genai` SDK）访问 Gemini 模型。内置模型包括 Gemini 3.1 Pro Preview、Gemini 3 Flash Preview、Gemini 3.1 Flash Lite Preview、Gemini 2.5 Pro、Gemini 2.5 Flash、Gemini 2.5 Flash Lite 和 Gemini 2.0 Flash。还可通过 API 自动发现更多模型。

**前置条件：**

- 从 [Google AI Studio](https://aistudio.google.com/apikey) 获取 Gemini API Key。

**在控制台中配置：**

1. 打开控制台，进入 **设置 → 模型**。
2. 找到 **Google Gemini** 提供商卡片，点击 **设置**。输入你的 **API Key**，点击 **保存**。
3. 保存后卡片状态变为 **可用**。该提供商支持 **模型发现** — 点击 **模型** 可自动从 API 发现可用的 Gemini 模型。
4. 在上方的 **LLM 配置** 中，**提供商** 下拉菜单选择 **Google Gemini**，**模型** 下拉菜单选择目标模型（如 `gemini-2.5-flash`），点击 **保存**。

**使用 CLI 配置：**

```bash
# 配置 API Key
copaw models config-key gemini

# 将 Gemini 设为活跃 LLM
copaw models set-llm
```

> **提示：** 具有思考能力的 Gemini 模型（如 Gemini 3.1 Pro、Gemini 2.5 Pro、Gemini 2.5 Flash）支持扩展推理。CoPaw 会自动处理这些模型返回的思考块和思考签名。

## 本地提供商（llama.cpp / MLX）

本地提供商在本地运行模型，**无需 API Key**，数据不出本机。

**前置条件：**

- 在CoPaw所在环境中安装对应后端：
  - llama.cpp：`pip install 'copaw[llamacpp]'`
  - MLX：`pip install 'copaw[mlx]'`

1. 在控制台的模型页面可以找到 llama.cpp 和 MLX 对应的卡片。

   ![card](https://img.alicdn.com/imgextra/i1/O1CN01EtKkuC1IJstIvaIQO_!!6000000000873-2-tps-3802-1968.png)

2. 点击目标本地提供商（以llama.cpp为例）卡片的 **模型**，选择 **下载模型**。

   ![download](https://img.alicdn.com/imgextra/i2/O1CN01TfqIum1aqYDx1CRQj_!!6000000003381-2-tps-3802-1968.png)

3. 填写 **仓库 ID**，并选择 **来源**，点击 **下载模型**。

   ![id](https://img.alicdn.com/imgextra/i4/O1CN01B8vx0L1xFD5z5RQR3_!!6000000006413-2-tps-3802-1968.png)

4. 可以看到正在下载模型，需要等待一段时间。

   ![wait](https://img.alicdn.com/imgextra/i1/O1CN01Tz3UxQ1QH9SCEiCs1_!!6000000001950-2-tps-3802-1968.png)

5. 模型下载完成后，可以看到本地提供商卡片右上角转为 **可用** 状态。

   ![avai](https://img.alicdn.com/imgextra/i3/O1CN01gOF4c41yE7lwD1O1a_!!6000000006546-2-tps-3802-1968.png)

6. 在上方的 **LLM 配置** 中，**提供商** 对应的下拉菜单中可以选择本地提供商，**模型** 对应的下拉菜单中可选择刚刚添加的模型。点击保存。

   ![model](https://img.alicdn.com/imgextra/i1/O1CN01nNiZyr262goHAs5Vx_!!6000000007604-2-tps-3802-1968.png)

7. 可以看到 LLM 配置右上角显示本地提供商和选择的模型名称。

   ![see](https://img.alicdn.com/imgextra/i4/O1CN01s8un7K1DzUnRvShaf_!!6000000000287-2-tps-3802-1968.png)

> 注：点击对应本地提供商卡片上的 **模型**，可以看到不同模型名称、大小、下载来源。如果想删除模型，点击对应模型最右侧的 **垃圾桶图标**，二次确认后即可删除。
>
> ![delete](https://img.alicdn.com/imgextra/i4/O1CN013E3HO01oUTl12fmcA_!!6000000005228-2-tps-3802-1968.png)

## Ollama 提供商

Ollama 提供商对接本机安装的 **Ollama 守护进程**，使用其中的模型，无需由 CoPaw 直接下载模型文件，列表会与 Ollama 自动同步。

**前置条件：**

- 从 [ollama.com](https://ollama.com) 安装 Ollama。
- 在 CoPaw所在虚拟环境中安装 Ollama：`pip install 'copaw[ollama]'`。

1. 在控制台的模型界面中，可以看到 ollama 提供商对应的卡片。

2. 点击右下角 **设置**，在配置 ollama 的页面中，填写 **API Key**。此处可随意填写一个内容，例如 ollama。点击 **保存**。

   ![set](https://img.alicdn.com/imgextra/i3/O1CN01pO67w51Fzc88k2KZl_!!6000000000558-2-tps-3802-1968.png)

3. 点击 **模型**，如果已经使用 Ollama 下载过一些模型，则可以看到对应的模型列表。如果还没有下载模型，或需要下载额外模型，点击 **下载模型**。

   ![download](https://img.alicdn.com/imgextra/i2/O1CN015THchk21SjFV0rlvk_!!6000000006984-2-tps-3802-1968.png)

4. 填写 **模型名称**，点击 **下载模型**。

   ![download](https://img.alicdn.com/imgextra/i3/O1CN01dDdg9Q1lSEyTnNODF_!!6000000004817-2-tps-3802-1968.png)

5. 可以看到进入模型下载状态，等待模型下载完成。

   ![wait](https://img.alicdn.com/imgextra/i2/O1CN01eek6ap1iIfr21Khxr_!!6000000004390-2-tps-3802-1968.png)

6. 下载完成后，可以在上方的 **LLM 配置** 中，**提供商** 对应的下拉菜单中可以选择 Ollama，**模型** 对应的下拉菜单中可选择想使用的模型。点击 **保存**。

   ![save](https://img.alicdn.com/imgextra/i4/O1CN019pRaJz1vqBqKf4uFn_!!6000000006223-2-tps-3802-1968.png)

7. 可以看到 LLM 配置右上角显示 Ollama 提供商和选择的模型名称。

   ![name](https://img.alicdn.com/imgextra/i1/O1CN01Qvokvp1xPHoDb9VV1_!!6000000006435-2-tps-3802-1968.png)

> 如果在过程中遇到 `Ollama SDK not installed. Install with: pip install 'copaw[ollama]'`的提示，请先确认是否已经在 ollama.com 下载 Ollama，并在 CoPaw所在虚拟环境中执行过 `pip install 'copaw[ollama]'`。如果想删除某个模型，点击 Ollama 卡片右下角的 **模型**，在模型列表中，点击想要删除的模型右侧的 **垃圾桶按钮**，二次确认后即可删除。
>
> **Docker 用户：** 如果 CoPaw 运行在 Docker 容器中，`localhost` 指向的是容器自身而非宿主机。请将 Ollama 的 Base URL 改为 `http://host.docker.internal:11434`（并在 `docker run` 命令中添加 `--add-host=host.docker.internal:host-gateway`）。详见 [README 的 Docker 章节](https://github.com/agentscope-ai/CoPaw#使用-docker)。
>
> ![delete](https://img.alicdn.com/imgextra/i2/O1CN01p2o85m1Ul9rkY87PS_!!6000000002557-2-tps-3802-1968.png)

## LM Studio 提供商

LM Studio 提供商连接 **LM Studio** 桌面应用内置的 OpenAI 兼容服务器。模型在 LM Studio 的图形界面中管理，CoPaw 通过 `/v1/models` 端点自动发现已加载的模型。

**前置条件：**

- 从 [lmstudio.ai](https://lmstudio.ai) 安装 LM Studio。
- 在 LM Studio 中加载模型并启动本地服务器（默认地址：`http://localhost:1234`）。

1. 在控制台的模型页面中，可以看到 LM Studio 提供商对应的卡片。

2. 点击右下角 **设置**，默认 Base URL 为 `http://localhost:1234/v1`。如果你在 LM Studio 中修改了端口，请相应调整。点击 **保存**。

3. 点击 **模型** 查看 LM Studio 中当前已加载的模型。如有需要，也可以手动添加模型 ID。

4. 在上方的 **LLM 配置** 中，**提供商** 对应的下拉菜单中选择 LM Studio，**模型** 对应的下拉菜单中选择想使用的模型。点击 **保存**。

> **提示：** LM Studio 默认不需要 API Key。如果你在 LM Studio 中启用了认证功能，请在 **API Key** 字段中填入对应的密钥。模型必须在 LM Studio 的图形界面中加载后才会在 CoPaw 中显示。
>
> **重要 — 上下文长度：** LM Studio 加载模型时默认的上下文长度较小（通常为 2048 或 4096 tokens）。CoPaw 的系统提示词（AGENTS.md + SOUL.md + PROFILE.md）可能会超过此限制，导致报错 _"The number of tokens to keep from the initial prompt is greater than the context length"_。解决方法：**在 LM Studio 中卸载模型，然后以更大的上下文长度重新加载**（建议 16384 及以上）。可以在 LM Studio 图形界面中调整（模型设置 → Context Length），也可以通过 CLI 操作：`lms unload --all && lms load <model> -c 16384`。
>
> **Docker 用户：** 如果 CoPaw 运行在 Docker 容器中，`localhost` 指向的是容器自身而非宿主机。请将 LM Studio 的 Base URL 改为 `http://host.docker.internal:1234/v1`（并在 `docker run` 命令中添加 `--add-host=host.docker.internal:host-gateway`）。详见 [README 的 Docker 章节](https://github.com/agentscope-ai/CoPaw#使用-docker)。

## 添加自定义提供商

1. 在控制台的模型页面点击 **添加提供商**。

   ![add](https://img.alicdn.com/imgextra/i4/O1CN01uZY4Im1pPjGXjNNb3_!!6000000005353-2-tps-3786-1980.png)

2. 填写 **提供商 ID** 和 **显示名称**，点击 **创建**。

   ![create](https://img.alicdn.com/imgextra/i1/O1CN01iTunEK1PtnFqTgzq5_!!6000000001899-2-tps-3786-1980.png)

3. 可以看见新添加的提供商卡片。

   ![card](https://img.alicdn.com/imgextra/i3/O1CN01s7fhvC1o4NBKCbAs1_!!6000000005171-2-tps-3786-1980.png)

4. 点击设置，填写 **Base URL** 和 **API Key**，点击 **保存**。

   ![save](https://img.alicdn.com/imgextra/i4/O1CN01VgJ2R01mLCVDDCVzR_!!6000000004937-2-tps-3786-1980.png)

5. 可以看到自定义提供商卡片中已经显示刚刚配置的 Base_URL 和 API Key，但此时右上角仍显示 **不可用**， 还需要配置模型。

   ![model](https://img.alicdn.com/imgextra/i2/O1CN01x47yH21X7GD8F5LzJ_!!6000000002876-2-tps-3786-1980.png)

6. 点击 **模型**，填写 **模型 ID**，点击 **添加模型**。

   ![add](https://img.alicdn.com/imgextra/i2/O1CN01binEay24FqxhNg8uP_!!6000000007362-2-tps-3786-1980.png)

7. 此时可见自定义提供商为 **可见**。在上方的 **LLM 配置** 中，**提供商** 对应的下拉菜单中可以选择自定义提供商，**模型** 对应的下拉菜单中可选择刚刚添加的模型。点击 **保存**。

   ![model](https://img.alicdn.com/imgextra/i4/O1CN01UHVBLo1UpjpIOkG9D_!!6000000002567-2-tps-3786-1980.png)

8. 可以看到 LLM 配置右上角显示自定义提供商的 ID 和选择的模型名称。

   ![save](https://img.alicdn.com/imgextra/i1/O1CN01Ltbgni23LydqhxVUX_!!6000000007240-2-tps-3786-1980.png)

> 注：如果无法成功配置，请重点检查 **Base URL，API Key 和 模型 ID** 是否填写正确，尤其是模型的大小写。如果想删除自定义提供商，在对应卡片右下角点击 **删除提供商**，二次确认后可成功删除。
>
> ![delete](https://img.alicdn.com/imgextra/i4/O1CN01r43eMv28On9egxjRz_!!6000000007923-2-tps-3412-1952.png)
