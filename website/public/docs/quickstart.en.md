# Quick start

This section describes multiple ways to install CoPaw:

| Installation Method   | Best For                                      | Advantages                                                  | Prerequisites         |
| --------------------- | --------------------------------------------- | ----------------------------------------------------------- | --------------------- |
| **Script install**    | Users who don't want manual environment setup | Zero configuration, automatic Python environment management | None                  |
| **pip install**       | Developers familiar with Python               | Flexible environment control, easy for development          | Python 3.10~3.13      |
| **Desktop app**       | Users unfamiliar with command line            | Double-click to use, graphical interface                    | None                  |
| **ModelScope Studio** | No local environment or quick trial           | One-click deploy, cloud running, no installation            | ModelScope account    |
| **Docker**            | Containerized deployment or production        | Environment isolation, easy migration                       | Docker                |
| **Alibaba Cloud ECS** | Stable cloud operation                        | One-click deploy, stable and reliable                       | Alibaba Cloud account |

> 📖 Please read [Introduction](./intro) first. After installation and startup, check out [Console](./console).

> 💡 **Key steps after installation and startup**:
>
> 1. Access [Console](./console) in your browser (`http://127.0.0.1:8088/`)
> 2. **Configure models** (required): Settings → Models → Configure API Key or download local models
> 3. Start chatting to test
> 4. (Optional) Configure channels to chat in DingTalk, Feishu, QQ, etc. See [Channels](./channels)

---

## Option 1: Script install

No Python required — the installer handles everything automatically using [uv](https://docs.astral.sh/uv/).

### Step 1: Install

**macOS / Linux:**

```bash
curl -fsSL https://copaw.agentscope.io/install.sh | bash
```

Then open a new terminal (or run `source ~/.zshrc` / `source ~/.bashrc`).

**Windows (CMD):**

```cmd
curl -fsSL https://copaw.agentscope.io/install.bat -o install.bat && install.bat
```

**Windows (PowerShell):**

```powershell
irm https://copaw.agentscope.io/install.ps1 | iex
```

Then open a new terminal (the installer adds CoPaw to your PATH automatically).

> **⚠️ Special Notice for Windows Enterprise LTSC Users**
>
> If you are using Windows LTSC or an enterprise environment governed by strict security policies, PowerShell may run in **Constrained Language Mode**, potentially causing the following issues:
>
> 1. **If using CMD (.bat): Script executes successfully but fails to write to `Path`**
>
>    The script completes file installation. Due to **Constrained Language Mode**, it cannot automatically update environment variables. Manually configure as follows:
>
>    - **Locate the installation directory**:
>      - Check if `uv` is available: Enter `uv --version` in CMD. If a version number appears, **only configure the CoPaw path**. If you receive `'uv' is not recognized as an internal or external command, operable program or batch file,` configure both paths.
>      - uv path (choose one based on installation location; fill if `uv` is unavailable): Typically `%USERPROFILE%\.local\bin`, `%USERPROFILE%\AppData\Local\uv`, or the `Scripts` folder within your Python installation directory
>      - CoPaw path: Typically `%USERPROFILE%\.copaw\bin`.
>    - **Manually add to the system's Path environment variable**:
>      - Press `Win + R`, type `sysdm.cpl` and press Enter to open System Properties.
>      - Click "Advanced" → "Environment Variables".
>      - Under "System variables", locate and select `Path`, then click "Edit".
>      - Click "New", enter both directory paths sequentially, then click OK to save.
>
> 2. **If using PowerShell (.ps1): Script execution interrupted**
>
> Due to **Constrained Language Mode**, the script may fail to automatically download `uv`.
>
> - **Manually install uv**: Refer to [GitHub Release](https://github.com/astral-sh/uv/releases) to download `uv.exe` and place it in `%USERPROFILE%\.local\bin` or `%USERPROFILE%\AppData\Local\uv`; or ensure Python is installed and run `python -m pip install -U uv`.
> - **Configure `uv` environment variables**: Add the `uv` directory and `%USERPROFILE%\.copaw\bin` to your system's `Path` variable.
> - **Re-run the installation**: Open a new terminal and execute the installation script again to complete the `CoPaw` installation.
> - **Configure the `CoPaw` environment variable**: Add `%USERPROFILE%\.copaw\bin` to your system's `Path` variable.

You can also specify options:

**macOS / Linux:**

```bash
# Install a specific version
curl -fsSL ... | bash -s -- --version 0.0.2

# Install from source (dev/testing)
curl -fsSL ... | bash -s -- --from-source
```

**Windows (PowerShell):**

```powershell
# Install a specific version
.\install.ps1 -Version 0.0.2

# Install from source (dev/testing)
.\install.ps1 -FromSource
```

To upgrade, simply re-run the install command. To uninstall, run `copaw uninstall`.

### Step 2: Initialize

Generate `config.json` and `HEARTBEAT.md` in the working directory (default
`~/.copaw`). Two options:

- **Quick with defaults** (no interaction, good for running first then editing config):
  ```bash
  copaw init --defaults
  ```
- **Interactive initialization** (prompts for heartbeat interval, target, active hours, and optional channel and Skills setup):
  ```bash
  copaw init
  ```
  See [CLI - Getting started](./cli#getting-started).

To overwrite existing config, use `copaw init --force` (you will be prompted).
After initialization, if no channel is enabled yet, follow the documentation in
[Channels](./channels) to add DingTalk, Feishu, QQ, etc.

### Step 3: Start the server

```bash
copaw app
```

The server listens on `127.0.0.1:8088` by default. If you've already configured
channels, CoPaw will reply there. Otherwise, you can complete this section
first and then configure channels.

---

## Option 2: pip install

If you prefer managing Python yourself (requires Python >= 3.10, < 3.14):

```bash
pip install copaw
```

Optional: create and activate a virtual environment first (`python -m venv .venv`,
then `source .venv/bin/activate` on Linux/macOS or `.venv\Scripts\Activate.ps1`
on Windows). This installs the `copaw` command.

Then follow [Step 2: Initialize](#step-2-initialize) and [Step 3: Start the server](#step-3-start-the-server) above.

---

## Option 3: Desktop application

If you're not comfortable with command-line tools, you can download and use
CoPaw's desktop application without manually configuring Python environments
or running commands.

### Features

- ✅ **Zero configuration**: Download and double-click to run, no need to install Python or configure environment variables
- ✅ **Cross-platform**: Supports Windows 10+ and macOS 14+ (Apple Silicon recommended)
- ✅ **Visual interface**: Automatically opens browser interface, no need to manually enter addresses

### Download and usage

1. **Download the installer**
   Go to [GitHub Releases](https://github.com/agentscope-ai/CoPaw/releases) to download the version for your system:

   - Windows: `CoPaw-Setup-<version>.exe`
   - macOS: `CoPaw-<version>-macOS.zip`

2. **Install and launch**

   - **Windows**: Double-click the `.exe` file to install following the wizard, then double-click the desktop shortcut to launch
   - **macOS**: Extract the `.zip` to get `CoPaw.app`, first time requires right-click and select "Open" to bypass system security restrictions

3. **First launch note**
   The first launch may take 10-60 seconds (depending on your system configuration).
   The application needs to initialize the Python environment and load dependencies.
   Please wait patiently for the browser window to open automatically.

### Complete guide

Desktop applications involve system permissions, security prompts, debug mode,
and other details. Please see the **[Complete Desktop Application Guide](./desktop)**
to learn about:

- Windows two launch modes (Normal vs Debug)
- macOS how to bypass system security restrictions (3 methods)
- Common issues and solutions
- Log viewing and issue reporting

---

## Option 4: ModelScope Studio one-click setup (no installation)

If you don't want to install Python locally, you can deploy CoPaw to the cloud
through ModelScope Studio:

1. First go to [ModelScope](https://modelscope.cn/register?back=%2Fhome) to register and log in;
2. Open [CoPaw Studio](https://modelscope.cn/studios/fork?target=AgentScope/CoPaw) and complete the one-click setup.

**Important**: Set your Studio to **non-public**, or others may control your CoPaw.

---

## Option 5: Docker

Images are on **Docker Hub** (`agentscope/copaw`). Image tags: `latest` (stable);
`pre` (PyPI pre-release). Also available on Alibaba Cloud ACR for users in China:
`agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/copaw` (same tags).

Pull and run:

```bash
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 \
  -v copaw-data:/app/working \
  -v copaw-secrets:/app/working.secret \
  agentscope/copaw:latest
```

Then open **http://127.0.0.1:8088/** in your browser for the Console. Config,
memory, and skills are stored in the `copaw-data` volume; model configurations
and API keys are stored in the `copaw-secrets` volume. To pass API keys, add
`-e DASHSCOPE_API_KEY=xxx` or `--env-file .env` to `docker run`.

---

## Option 6: Deploy to Alibaba Cloud ECS

To deploy CoPaw on Alibaba Cloud, use the ECS one-click deployment:

1. Open the [CoPaw Alibaba Cloud ECS deployment link](https://computenest.console.aliyun.com/service/instance/create/cn-hangzhou?type=user&ServiceId=service-1ed84201799f40879884) and fill in the deployment parameters as prompted;
2. After parameter configuration, confirm the cost and create the instance. Once deployment is complete, you can get the access URL and use the service.

For detailed steps and instructions, see [Alibaba Cloud Developer Community: Deploy your AI assistant with CoPaw in 3 minutes](https://developer.aliyun.com/article/1713682).

---

## Verify installation (optional)

After the server starts, you can call the Agent API via HTTP to confirm the
environment is working. The endpoint is **POST** `/api/agent/process`, with
JSON body and SSE streaming support. Single-turn example:

```bash
curl -N -X POST "http://localhost:8088/api/agent/process" \
  -H "Content-Type: application/json" \
  -d '{"input":[{"role":"user","content":[{"type":"text","text":"Hello"}]}],"session_id":"session123"}'
```

Use the same `session_id` for multi-turn conversations.

---

## What to do next?

### Required steps

#### ✅ 1. Configure models (required)

CoPaw needs a large language model to work. You can choose either option:

**Option A: Use cloud models (requires API Key)**

1. In the Console, go to **Settings → Models**
2. Select a provider (such as DashScope, ModelScope, etc.)
3. Click the **Settings** button and enter your **API Key**
4. Click **Save**
5. In the top **Default LLM**, select the provider and specific model
6. Click **Save**

See [Models - Configure cloud providers](./models).

**Option B: Use local models (no API Key required, completely offline)**

1. Install local model backend:

- CoPaw Local (llama.cpp): download `llama.cpp` inside CoPaw Local provider settings, see [Models - Local providers Configuration](./models) for details.
- Ollama: install Ollama from [Ollama website](https://ollama.com/download) and run the Ollama service.
- LM Studio: install LM Studio from [LM Studio website](https://lmstudio.ai/download) and run the LM Studio service.

2. Download models:

- For CoPaw Local (llama.cpp), you can download models directly from the provider settings in the Console, or manually place GGUF model files in the local models directory (default `~/.copaw/local_models/models/<org>/<model>`, for example: `~/.copaw/local_models/models/Qwen/Qwen3-0.6B-GGUF`).
- For Ollama and LM Studio, you need to add models in their respective services first, then CoPaw can automatically fetch the model list and connect to them.

3. Select the local provider and model in the Console

After configuring the local model, you can select it in the Console's **Default LLM** settings or in the **Chat** page.

#### 🎯 2. Test chat in Console

After model configuration is complete, send a message in the Console's **Chat**
page to test functionality and confirm CoPaw can reply normally.

---

### Optional extensions

After configuring models and testing successfully, you can extend as needed:

#### 📱 Connect messaging channels

Chat with CoPaw in DingTalk, Feishu, QQ, Discord, iMessage, and other apps:

1. In the Console, go to **Control → Channels**
2. Select the channel to connect
3. Follow the [Channels](./channels) documentation to obtain credentials and fill them in
4. After saving, you can send messages to CoPaw in the corresponding app

#### 🔧 Enable and extend skills

Give CoPaw more capabilities (PDF processing, Office documents, news summaries, etc.):

- In the Console, go to **Agent → Skill Pool** or **Agent → Skills**
- Import built-in skills, import from Skill Hub, or create custom skills
- See [Skills](./skills)

#### 🔌 Connect MCP tools

Extend external tool capabilities through MCP (Model Context Protocol):

- In the Console, go to **Agent → MCP**
- Create MCP client and connect to external tool servers
- See [MCP](./mcp)

#### ⏰ Set up scheduled tasks and heartbeat

Let CoPaw execute tasks automatically:

- **Scheduled tasks**: Create in Console **Control → Scheduled tasks**, or use `copaw cron` command in [CLI](./cli)
- **Heartbeat**: Configure scheduled check-ins or digests, see [Heartbeat](./heartbeat)

#### 👥 Create multi-agent

Create multiple specialized assistants, each with their own role or collaborating:

- Create new agents in Console **Settings → Agent Management**
- Each agent has independent configuration, memory, skills, and conversation history
- Enable collaboration skills to let agents communicate with each other
- See [Multi-Agent](./multi-agent)

#### 📂 Adjust working directory

To change the location of configuration files or working directory, see [Config & working directory](./config).
