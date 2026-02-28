# FAQ

This page collects the most frequently asked questions from the community.
Click a question to expand the answer.

---

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
docker run -p 8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

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
docker run -p 8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

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

### Open-source repository

CoPaw is open source. Official repository:
`https://github.com/agentscope-ai/CoPaw`

### Where to check latest version upgrade details

You can check version changes in CoPaw GitHub
[Releases](https://github.com/agentscope-ai/CoPaw/releases).

### How to configure models

In Console, go to **Settings -> Models**. See
[Console -> Models](https://copaw.agentscope.io/docs/console#models) for
details.

- Cloud models: fill provider API key (ModelScope, DashScope, or custom), then
  choose the active model.
- Local models: supports `llama.cpp`, `MLX`, and Ollama. After download, select
  the active model on the same page.

You can also use `copaw models` CLI commands for configuration, download, and
switching. See
[CLI -> Models and Environment Variables -> copaw models](https://copaw.agentscope.io/docs/cli#copaw-models).

### How to manage Skills

Go to **Agent -> Skills** in Console. You can enable/disable Skills, create
custom Skills, and import Skills from Skills Hub. See
[Skills](https://copaw.agentscope.io/docs/skills).

### How to configure MCP

Go to **Agent -> MCP** in Console. You can enable/disable/delete/create MCP
clients there. See [MCP](https://copaw.agentscope.io/docs/mcp).

### Common error

1. Error pattern: `You didn't provide an API key`

Error detail:

```
Error: Unknown agent error: AuthenticationError: Error code: 401 - {'error': {'message': "You didn't provide an API key. You need to provide your API key in an Authorization header using Bearer auth (i.e. Authorization: Bearer YOUR_KEY). ", 'type': 'invalid_request_error', 'param': None, 'code': None}, 'request_id': 'ebc81304-2b7d-9da1-ba88-2868415d48ff'}
```

Cause: model API key is not configured. Get an API key and configure it in
**Console -> Settings -> Models**.
