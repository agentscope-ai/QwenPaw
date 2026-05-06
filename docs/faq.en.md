# FAQ

This page collects the most frequently asked questions from the community.
Click a question to expand the answer.

---

### QwenPaw vs OpenClaw: Feature Comparison

Please check the [Comparison](/docs/comparison) page for detailed feature comparison.

### How to install QwenPaw

QwenPaw supports multiple installation methods. See
[Quick Start](https://qwenpaw.agentscope.io/docs/quickstart) for details:

1. One-line installer (sets up Python automatically)

```
# macOS / Linux:
curl -fsSL https://qwenpaw.agentscope.io/install.sh | bash
# Windows (PowerShell):
irm https://qwenpaw.agentscope.io/install.ps1 | iex
# For latest instructions, refer to docs and prefer pip if needed.
```

2. Install with pip

Python version requirement: >= 3.10, < 3.14

```
pip install qwenpaw
```

3. Install with Docker

If Docker is installed, run the following commands and then open
`http://127.0.0.1:8088/` in your browser:

```
docker pull agentscope/qwenpaw:latest
docker run -p 127.0.0.1:8088:8088 \
  -v qwenpaw-data:/app/working \
  -v qwenpaw-secrets:/app/working.secret \
  -v qwenpaw-backups:/app/working.backups \
  agentscope/qwenpaw:latest
```

> **⚠️ Special Notice for Windows Enterprise LTSC Users**
>
> If you are using Windows LTSC or an enterprise environment governed by strict security policies, PowerShell may run in **Constrained Language Mode**, potentially causing the following issue:
>
> 1. **If using CMD (.bat): Script executes successfully but fails to write to `Path`**
>
>    The script completes file installation. Due to **Constrained Language Mode**, it cannot automatically update environment variables. Manually configure as follows:
>
>    - **Locate the installation directory**:
>      - Check if `uv` is available: Enter `uv --version` in CMD. If a version number appears, **only configure the QwenPaw path**. If you receive the prompt `'uv' is not recognized as an internal or external command, operable program or batch file,` configure both paths.
>      - uv path (choose one based on installation location; use if step 1 fails): Typically `%USERPROFILE%\.local\bin`, `%USERPROFILE%\AppData\Local\uv`, or the `Scripts` folder within your Python installation directory
>      - QwenPaw path: Typically located at `%USERPROFILE%\.qwenpaw\bin`.
>    - **Manually add to the system's Path environment variable**:
>      - Press `Win + R`, type `sysdm.cpl` and press Enter to open System Properties.
>      - Click “Advanced” -> “Environment Variables”.
>      - Under “System variables”, locate and select `Path`, then click “Edit”.
>      - Click “New”, enter both directory paths sequentially, then click OK to save.
>
> 2. **If using PowerShell (.ps1): Script execution interrupted**
>
> Due to **Constrained Language Mode**, the script may fail to automatically download `uv`.
>
> - **Manually install uv**: Refer to the [GitHub Release](https://github.com/astral-sh/uv/releases) to download `uv.exe` and place it in `%USERPROFILE%\.local\bin` or `%USERPROFILE%\AppData\Local\uv`; or ensure Python is installed and run `python -m pip install -U uv`.
> - **Configure `uv` environment variables**: Add the `uv` directory and `%USERPROFILE%\.qwenpaw\bin` to your system's `Path` variable.
> - **Re-run the installation**: Open a new terminal and execute the installation script again to complete the `QwenPaw` installation.
> - **Configure the `QwenPaw` environment variable**: Add `%USERPROFILE%\.qwenpaw\bin` to your system's `Path` variable.

### How to update QwenPaw

To update QwenPaw, use the method matching your installation type:

1. If installed via one-line script, re-run the installer to upgrade.

2. If installed via pip, run:

```
qwenpaw update
```

3. If installed from source, pull the latest code and reinstall:

```
cd QwenPaw
git pull origin main
cd console && npm ci && npm run build
cd .. && mkdir -p src/qwenpaw/console
cp -R console/dist/. src/qwenpaw/console/
pip install -e .
```

4. If using Docker, pull the latest image and restart the container:

```
docker pull agentscope/qwenpaw:latest
docker run -p 127.0.0.1:8088:8088 \
  -v qwenpaw-data:/app/working \
  -v qwenpaw-secrets:/app/working.secret \
  -v qwenpaw-backups:/app/working.backups \
  agentscope/qwenpaw:latest
```

5. If using the Desktop app (Windows `.exe` or macOS `.zip`), you currently need to uninstall and reinstall:
   - Uninstall QwenPaw on your machine
   - Download the latest build: https://qwenpaw.agentscope.io/downloads
   - Reinstall

After upgrading, restart the service with `qwenpaw app`.

If you previously used CoPaw, upgrading to QwenPaw only requires downloading the latest QwenPaw. No extra migration is needed; your configuration, memory, skills, and other data from the CoPaw era continue to work.

### How to initialize and start QwenPaw service

Recommended quick initialization:

```bash
qwenpaw init --defaults
```

Start service:

```bash
qwenpaw app
```

The default Console URL is `http://127.0.0.1:8088/`. After quick init, you can
open Console and customize settings. See
[Quick Start](https://qwenpaw.agentscope.io/docs/quickstart).

### Port 8088 conflict on Windows

On Windows, Hyper-V and WSL2 may reserve certain port ranges, which can conflict
with QwenPaw's default port **8088**. This affects all installation methods
(pip, script, Docker, desktop app).

**Symptoms:**

- Error: `Address already in use` or `OSError: [Errno 98] Address already in use`
- Error: `An attempt was made to access a socket in a way forbidden by its access permissions`
- QwenPaw fails to start, or browser cannot connect to `http://127.0.0.1:8088/`

**Check if port 8088 is reserved on Windows:**

Open PowerShell or CMD and run:

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

If 8088 appears in the excluded ranges, it's reserved by the system.

**Solution: Use a different port**

**For pip / script installation:**

```bash
qwenpaw app --port 8090
```

Then open `http://127.0.0.1:8090/` in your browser.

**For Docker:**

```bash
docker run -p 127.0.0.1:8090:8088 \
  -v qwenpaw-data:/app/working \
  -v qwenpaw-secrets:/app/working.secret \
  -v qwenpaw-backups:/app/working.backups \
  agentscope/qwenpaw:latest
```

Then open `http://127.0.0.1:8090/` in your browser.

**For Windows Desktop App:**

Currently, the desktop app uses port 8088 by default. If you encounter this
issue, you can:

1. Run `qwenpaw app --port 8090` from a terminal instead
2. Or exclude port 8088 from Windows reserved ranges (requires administrator
   privileges and may affect other services)

**Advanced: Prevent Windows from reserving port 8088**

Run the following in an elevated PowerShell (run as Administrator):

```powershell
# Exclude port 8088 from the dynamic port range
netsh int ipv4 set dynamicport tcp start=49152 num=16384
# Restart Windows for changes to take effect
```

> ⚠️ **Warning**: This changes system-wide port configuration. Only do this if
> you understand the implications.

### APITimeoutError when running QwenPaw in WSL2 (NAT mode)

When running QwenPaw inside WSL2 with NAT networking (especially when a VPN is
active on the Windows host), you may encounter repeated timeouts:

```
agent error: APITimeoutError: Request timed out.
```

**Root cause:** WSL2's default network MTU (1500) is too large for the NAT
tunnel, causing packets to be silently dropped when a VPN or certain network
configurations are in use.

**Solution:** Lower the WSL2 network interface MTU to **1350**.

1. **Check the current MTU inside WSL2:**

   ```bash
   ip link show eth0 | grep mtu
   ```

2. **Set MTU to 1350 (temporary, resets on reboot):**

   ```bash
   sudo ip link set eth0 mtu 1350
   ```

3. **Make the change permanent** by adding a boot command to `/etc/wsl.conf`:

   ```ini
   [boot]
   command = /sbin/ip link set eth0 mtu 1350
   ```

   Then restart WSL2 from PowerShell or CMD:

   ```powershell
   wsl --shutdown
   ```

4. **Verify** the change took effect:

   ```bash
   ip link show eth0 | grep mtu
   # should show: mtu 1350
   ```

After this, QwenPaw should be able to communicate with model providers
normally.

### Open-source repository

QwenPaw is open source. Official repository:
`https://github.com/agentscope-ai/QwenPaw`

### Where to check latest version upgrade details

See the site [Release notes](https://qwenpaw.agentscope.io/release-notes/?lang=en)
or QwenPaw GitHub [Releases](https://github.com/agentscope-ai/QwenPaw/releases).

### How to configure models

In Console, go to **Settings → Models** to configure. See the
[Models](https://qwenpaw.agentscope.io/docs/models) doc for details:

- Cloud models: enter the provider API key (e.g. ModelScope, DashScope, or a
  custom provider).
- Local models: supports `llama.cpp`, LM Studio and Ollama.

After configuration, choose the target provider and model under **Default LLM**
at the top of the Models page and **Save** — that becomes the global default.

To use a different model per agent, switch the agent with the selector at the top-left of Console, then pick a model in the top-right of the **Chat** page for that
agent.

You can also use `qwenpaw models` for setup, downloads, and switching. See
[CLI → Models and environment variables → qwenpaw models](https://qwenpaw.agentscope.io/docs/cli#qwenpaw-models).

### How to use QwenPaw-Flash series models

QwenPaw-Flash is a family of models tuned by the QwenPaw team for QwenPaw's core
usage scenarios. It comes in 2B, 4B, and 9B sizes. In addition to the original
models, each version also provides 4-bit and 8-bit quantized variants to suit
different VRAM budgets and performance needs.

QwenPaw-Flash models are currently open-sourced on
[ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model) and
[Hugging Face](https://huggingface.co/agentscope-ai/models), and can be
downloaded directly from either platform.

All built-in local providers in QwenPaw can be used with QwenPaw-Flash models:

#### QwenPaw Local (llama.cpp)

In the QwenPaw Local model interface, simply choose a QwenPaw-Flash model to
download and start it.

![Start Model](https://img.alicdn.com/imgextra/i4/O1CN019nuWG21Zy36HLYRWR_!!6000000003262-2-tps-1344-1678.png)

> QwenPaw Local is still in beta. Compatibility across different devices and
> runtime stability are still being improved. If you run into issues while
> using it, please open an issue on GitHub.
> If QwenPaw Local does not work properly in your environment, we recommend
> deploying QwenPaw-Flash with Ollama or LM Studio first.

#### Ollama

1. Download a quantized QwenPaw-Flash model from
   [ModelScope](https://www.modelscope.cn/organization/AgentScope?tab=model)
   or [Hugging Face](https://huggingface.co/agentscope-ai/models). These model
   variants use suffixes such as `Q8_0` or `Q4_K_M`, for example
   [QwenPaw-Flash-4B-Q4_K_M](https://www.modelscope.cn/models/AgentScope/QwenPaw-Flash-4B-Q4_K_M).

   - Download with ModelScope CLI:

     ```bash
     modelscope download --model AgentScope/QwenPaw-Flash-4B-Q4_K_M README.md --local_dir ./dir
     ```

   - Download with Hugging Face CLI:

     ```bash
     hf download agentscope-ai/QwenPaw-Flash-4B-Q4_K_M --local_dir ./dir
     ```

2. Download and install Ollama from the [official site](https://ollama.com/download),
   then start it.

3. Import the downloaded model into Ollama with the `ollama create` command:

Create a text file named `qwenpaw-flash.txt` with the following contents. Replace
`/path/to/your/qwenpaw-xxx.gguf` with the absolute path to the `.gguf` file in
the QwenPaw-Flash model repository you downloaded:

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

Then run the following command in your terminal:

```bash
ollama create qwenpaw-flash -f qwenpaw-flash.txt
```

4. In QwenPaw model settings, choose the Ollama provider, then automatically load
   the model on the Models page.

#### LM Studio

1. Follow step 1 in the Ollama section above to download an appropriate
   quantized QwenPaw-Flash model.

2. Download and install LM Studio from the [official site](https://lmstudio.ai/),
   then start it.

3. Import the downloaded model into LM Studio with the following command:

```bash
lms import /path/to/your/qwenpaw-xxx.gguf -c -y --user-repo AgentScope/QwenPaw-Flash
```

4. In QwenPaw model settings, choose the LM Studio provider, then automatically
   load the model on the Models page.

### When using models deployed with Ollama / LM Studio, why can't QwenPaw complete multi-turn interactions, complex tool calls, or remember earlier instructions?

In most cases, this is not a QwenPaw bug. The root cause is usually that the
model's context length is configured too small.

When you deploy a local model with Ollama or LM Studio, if the model's
`context length` is too low, QwenPaw may show problems such as:

- failing to sustain multi-turn conversations reliably
- losing context during complex tool calls
- forgetting instructions given in earlier turns
- drifting away from the task during long-running interactions

**How to fix it:**

- Before running QwenPaw, set the model's `context length` to **at least 32K**
- For more complex tasks, frequent tool calls, or longer conversations, you
  may need a value **higher than 32K**

> ⚠️ **Before running QwenPaw, you must set the context length to 32K or higher**
>
> For local models deployed with Ollama or LM Studio, QwenPaw typically needs a
> context length of **32K or higher** to handle multi-turn interactions,
> complex tool calls, and long-context tasks reliably. In more demanding
> scenarios, an even larger context window may be required.
>
> Note that larger context windows can significantly increase VRAM / memory
> usage and compute cost, so make sure your local machine can handle it.

**Ollama configuration example:**

![Ollama context length configuration](https://img.alicdn.com/imgextra/i3/O1CN01JrqRjE1l6FxuO3IMl_!!6000000004769-2-tps-699-656.png)

**LM Studio configuration example:**

![LM Studio context length configuration](https://img.alicdn.com/imgextra/i4/O1CN01LWyG6o21E4Zovqv4G_!!6000000006952-2-tps-923-618.png)

### Troubleshooting scheduled (cron) tasks

In Console, go to **Control -> Cron Jobs** to create and manage scheduled tasks.

![cron](https://img.alicdn.com/imgextra/i3/O1CN01duPPPB1R0x495tRdY_!!6000000002050-2-tps-3822-2064.png)

The easiest way to create a cron job is to talk to QwenPaw in the channel where you want the results. For example, say: “Create a scheduled task that reminds me to drink water every five minutes.” You can then see the enabled job in Console.

If a scheduled task does not run as expected, try the following:

1. Confirm that the QwenPaw service is running.

2. Check that the task **Status** is **Enabled**.

   ![enable](https://img.alicdn.com/imgextra/i3/O1CN01XsJiIH1bIUOD4j9sF_!!6000000003442-2-tps-3236-880.png)

3. Check that **Dispatch Channel** is set to the channel where you want the result (e.g. console, dingtalk, feishu, discord, imessage).

   ![channel](https://img.alicdn.com/imgextra/i2/O1CN01JN4bq61WKFpzXrIcZ_!!6000000002769-2-tps-3230-876.png)

4. Check that **Dispatch Target User ID** and **Dispatch Target Session ID** are correct.

   ![id](https://img.alicdn.com/imgextra/i2/O1CN014BLaOC1YwO2onZK8U_!!6000000003123-2-tps-3236-874.png)

   In Console, go to **Control -> Sessions** and find the session you used when creating the task. To have the task reply in that session, the **User ID** and **Session ID** there must match the task’s **Dispatch Target User ID** and **Dispatch Target Session ID**.

   ![id](https://img.alicdn.com/imgextra/i2/O1CN01iZZhHZ1VeZnMzjlMm_!!6000000002678-2-tps-3236-1068.png)

5. If the task runs at the wrong time, check the **Schedule (Cron)** for the task.

   ![cron](https://img.alicdn.com/imgextra/i4/O1CN01TSodVd21msgJQvHkI_!!6000000007028-2-tps-3234-876.png)

6. To verify that the task was created and can run, click **Execute Now**. If it works, you should see the reply in the target channel. You can also ask QwenPaw: “Trigger the ‘drink water reminder’ task I just created.”

   ![exec](https://img.alicdn.com/imgextra/i4/O1CN01MkrSYn1mJpJshAO8n_!!6000000004934-2-tps-3224-878.png)

### How to manage Skills

Go to **Agent -> Skills** in Console. You can enable/disable Skills, create
custom Skills, and import Skills from Skills Hub. See
[Skills](https://qwenpaw.agentscope.io/docs/skills).

### How to configure MCP

Go to **Agent -> MCP** in Console. You can enable/disable/delete/create MCP
clients there. See [MCP](https://qwenpaw.agentscope.io/docs/mcp).

### Common errors

1. Error pattern: `You didn't provide an API key`

Error detail:

```
Error: Unknown agent error: AuthenticationError: Error code: 401 - {'error': {'message': "You didn't provide an API key. You need to provide your API key in an Authorization header using Bearer auth (i.e. Authorization: Bearer YOUR_KEY). ", 'type': 'invalid_request_error', 'param': None, 'code': None}, 'request_id': 'xxx'}
```

Cause 1: model API key is not configured. Get an API key and configure it in
**Console -> Settings -> Models**.

Cause 2: key is configured but still fails. In most cases, one of the
configuration fields is incorrect (for example `base_url`, `api key`, or model
name).

QwenPaw supports API keys obtained via DashScope Coding Plan. If it still fails,
please check:

- whether `base_url` is correct;
- whether the API key is copied completely (no extra spaces);
- whether the model name exactly matches the provider value (case-sensitive).

Reference for the correct key acquisition flow:
https://help.aliyun.com/zh/model-studio/coding-plan-quickstart#2531c37fd64f9

---

### How to get support when errors occur

To speed up troubleshooting and fixes, please open an
[issue](https://github.com/agentscope-ai/QwenPaw/issues) in the QwenPaw GitHub
repository and attach the full error message and any error detail file.

Console errors often include a path to an error detail file. For example:

Error: Unknown agent error: AuthenticationError: Error code: 401 - {'error': {'message': "You didn't provide an API key. You need to provide your API key in an Authorization header using Bearer auth (i.e. Authorization: Bearer YOUR_KEY). ", 'type': 'invalid_request_error', 'param': None, 'code': None}, 'request_id': 'xxx'}(Details: /var/folders/.../qwenpaw_query_error_qzbx1mv1.json)

Please upload that file (e.g. `/var/folders/.../qwenpaw_query_error_qzbx1mv1.json`)
and also provide your current model provider, model name, and QwenPaw version.
