# FAQ

This page collects the most frequently asked questions from the community.
Click a question to expand the answer.

---

### CoPaw vs OpenClaw: Feature Comparison

Please check the [Comparison](/docs/comparison) page for detailed feature comparison.

### How to install CoPaw

CoPaw supports multiple installation methods. See
[Quick Start](https://copaw.agentscope.io/docs/quickstart) for details:

1. One-line installer (sets up Python automatically)

```
# macOS / Linux:
curl -fsSL https://copaw.agentscope.io/install.sh | bash
# Windows (PowerShell):
irm https://copaw.agentscope.io/install.ps1 | iex
# For latest instructions, refer to docs and prefer pip if needed.
```

2. Install with pip

Python version requirement: >= 3.10, < 3.14

```
pip install copaw
```

3. Install with Docker

If Docker is installed, run the following commands and then open
`http://127.0.0.1:8088/` in your browser:

```
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 \
  -v copaw-data:/app/working \
  -v copaw-secrets:/app/working.secret \
  agentscope/copaw:latest
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
>      - Check if `uv` is available: Enter `uv --version` in CMD. If a version number appears, **only configure the CoPaw path**. If you receive the prompt `'uv' is not recognized as an internal or external command, operable program or batch file,` configure both paths.
>      - uv path (choose one based on installation location; use if step 1 fails): Typically `%USERPROFILE%\.local\bin`, `%USERPROFILE%\AppData\Local\uv`, or the `Scripts` folder within your Python installation directory
>      - CoPaw path: Typically located at `%USERPROFILE%\.copaw\bin`.
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
> - **Configure `uv` environment variables**: Add the `uv` directory and `%USERPROFILE%\.copaw\bin` to your system's `Path` variable.
> - **Re-run the installation**: Open a new terminal and execute the installation script again to complete the `CoPaw` installation.
> - **Configure the `CoPaw` environment variable**: Add `%USERPROFILE%\.copaw\bin` to your system's `Path` variable.

### How to update CoPaw

To update CoPaw, use the method matching your installation type:

1. If installed via one-line script, re-run the installer to upgrade.

2. If installed via pip, run:

```
pip install --upgrade copaw
```

3. If installed from source, pull the latest code and reinstall:

```
cd CoPaw
git pull origin main
pip install -e .
```

4. If using Docker, pull the latest image and restart the container:

```
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 \
  -v copaw-data:/app/working \
  -v copaw-secrets:/app/working.secret \
  agentscope/copaw:latest
```

5. If using the Windows Desktop App (exe), currently you need to uninstall and reinstall:
   - Uninstall CoPaw from your PC
   - Download the latest version from: https://github.com/agentscope-ai/CoPaw/releases
   - Reinstall

After upgrading, restart the service with `copaw app`.

### How to initialize and start CoPaw service

Recommended quick initialization:

```bash
copaw init --defaults
```

Start service:

```bash
copaw app
```

The default Console URL is `http://127.0.0.1:8088/`. After quick init, you can
open Console and customize settings. See
[Quick Start](https://copaw.agentscope.io/docs/quickstart).

### Port 8088 conflict on Windows

On Windows, Hyper-V and WSL2 may reserve certain port ranges, which can conflict
with CoPaw's default port **8088**. This affects all installation methods
(pip, script, Docker, desktop app).

**Symptoms:**

- Error: `Address already in use` or `OSError: [Errno 98] Address already in use`
- Error: `An attempt was made to access a socket in a way forbidden by its access permissions`
- CoPaw fails to start, or browser cannot connect to `http://127.0.0.1:8088/`

**Check if port 8088 is reserved on Windows:**

Open PowerShell or CMD and run:

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

If 8088 appears in the excluded ranges, it's reserved by the system.

**Solution: Use a different port**

**For pip / script installation:**

```bash
copaw app --port 8090
```

Then open `http://127.0.0.1:8090/` in your browser.

**For Docker:**

```bash
docker run -p 127.0.0.1:8090:8088 \
  -v copaw-data:/app/working \
  -v copaw-secrets:/app/working.secret \
  agentscope/copaw:latest
```

Then open `http://127.0.0.1:8090/` in your browser.

**For Windows Desktop App:**

Currently, the desktop app uses port 8088 by default. If you encounter this
issue, you can:

1. Run `copaw app --port 8090` from a terminal instead
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

### Open-source repository

CoPaw is open source. Official repository:
`https://github.com/agentscope-ai/CoPaw`

### Where to check latest version upgrade details

See the site [Release notes](https://copaw.agentscope.io/release-notes/?lang=en)
or CoPaw GitHub [Releases](https://github.com/agentscope-ai/CoPaw/releases).

### How to configure models

In Console, go to **Settings → Models** to configure. See the
[Models](https://copaw.agentscope.io/docs/models) doc for details:

- Cloud models: enter the provider API key (e.g. ModelScope, DashScope, or a
  custom provider).
- Local models: supports `llama.cpp`, `MLX`, and Ollama.

After configuration, choose the target provider and model under **Default LLM**
at the top of the Models page and **Save** — that becomes the global default.

To use a different model per agent, switch the agent with the selector at the
top of Console, then pick a model in the top-left of the **Chat** page for that
agent.

You can also use `copaw models` for setup, downloads, and switching. See
[CLI → Models and environment variables → copaw models](https://copaw.agentscope.io/docs/cli#copaw-models).

### When using models deployed with Ollama / LM Studio, why can't CoPaw complete multi-turn interactions, complex tool calls, or remember earlier instructions?

In most cases, this is not a CoPaw bug. The root cause is usually that the
model's context length is configured too small.

When you deploy a local model with Ollama or LM Studio, if the model's
`context length` is too low, CoPaw may show problems such as:

- failing to sustain multi-turn conversations reliably
- losing context during complex tool calls
- forgetting instructions given in earlier turns
- drifting away from the task during long-running interactions

**How to fix it:**

- Before running CoPaw, set the model's `context length` to **at least 32K**
- For more complex tasks, frequent tool calls, or longer conversations, you
  may need a value **higher than 32K**

> ⚠️ **Before running CoPaw, you must set the context length to 32K or higher**
>
> For local models deployed with Ollama or LM Studio, CoPaw typically needs a
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

![cron](https://img.alicdn.com/imgextra/i2/O1CN01sL8ZYj1QJtpXs9iKE_!!6000000001956-2-tps-3814-1954.png)

The easiest way to create a cron job is to talk to CoPaw in the channel where you want the results. For example, say: “Create a scheduled task that reminds me to drink water every five minutes.” You can then see the enabled job in Console.

If a scheduled task does not run as expected, try the following:

1. Confirm that the CoPaw service is running.

2. Check that the task **Status** is **Enabled**.

   ![enable](https://img.alicdn.com/imgextra/i4/O1CN01oggNyG1yQwrWKCnN7_!!6000000006574-2-tps-3020-762.png)

3. Check that **Dispatch Channel** is set to the channel where you want the result (e.g. console, dingtalk, feishu, discord, imessage).

   ![channel](https://img.alicdn.com/imgextra/i1/O1CN01RnjX7z1MHpZvVpjJq_!!6000000001410-2-tps-3020-762.png)

4. Check that **Dispatch Target User ID** and **Dispatch Target Session ID** are correct.

   ![id](https://img.alicdn.com/imgextra/i4/O1CN01QgvEDv290o1p3oaTv_!!6000000008006-2-tps-3020-762.png)

   In Console, go to **Control -> Sessions** and find the session you used when creating the task. To have the task reply in that session, the **User ID** and **Session ID** there must match the task’s **Dispatch Target User ID** and **Dispatch Target Session ID**.

   ![id](https://img.alicdn.com/imgextra/i3/O1CN01aqsLLR1eRb6m6WaGl_!!6000000003868-2-tps-3020-928.png)

5. If the task runs at the wrong time, check the **Schedule (Cron)** for the task.

   ![cron](https://img.alicdn.com/imgextra/i2/O1CN01iNoLp229bRiIdvJKK_!!6000000008086-2-tps-3020-778.png)

6. To verify that the task was created and can run, click **Execute Now**. If it works, you should see the reply in the target channel. You can also ask CoPaw: “Trigger the ‘drink water reminder’ task I just created.”

   ![exec](https://img.alicdn.com/imgextra/i3/O1CN01nGtc3p1o5kN0d01mf_!!6000000005174-2-tps-3020-778.png)

### How to manage Skills

Go to **Agent -> Skills** in Console. You can enable/disable Skills, create
custom Skills, and import Skills from Skills Hub. See
[Skills](https://copaw.agentscope.io/docs/skills).

### How to configure MCP

Go to **Agent -> MCP** in Console. You can enable/disable/delete/create MCP
clients there. See [MCP](https://copaw.agentscope.io/docs/mcp).

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

CoPaw supports API keys obtained via DashScope Coding Plan. If it still fails,
please check:

- whether `base_url` is correct;
- whether the API key is copied completely (no extra spaces);
- whether the model name exactly matches the provider value (case-sensitive).

Reference for the correct key acquisition flow:
https://help.aliyun.com/zh/model-studio/coding-plan-quickstart#2531c37fd64f9

---

### How to get support when errors occur

To speed up troubleshooting and fixes, please open an
[issue](https://github.com/agentscope-ai/CoPaw/issues) in the CoPaw GitHub
repository and attach the full error message and any error detail file.

Console errors often include a path to an error detail file. For example:

Error: Unknown agent error: AuthenticationError: Error code: 401 - {'error': {'message': "You didn't provide an API key. You need to provide your API key in an Authorization header using Bearer auth (i.e. Authorization: Bearer YOUR_KEY). ", 'type': 'invalid_request_error', 'param': None, 'code': None}, 'request_id': 'xxx'}(Details: /var/folders/.../copaw_query_error_qzbx1mv1.json)

Please upload that file (e.g. `/var/folders/.../copaw_query_error_qzbx1mv1.json`)
and also provide your current model provider, model name, and CoPaw version.
