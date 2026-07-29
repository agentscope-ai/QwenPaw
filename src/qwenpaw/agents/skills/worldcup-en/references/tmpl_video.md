# Universal Video Generation Workflow

When the user asks to **generate a video** or when the agent offers to create a visual highlight of their favorite team/player.

## ⚠️ MANDATORY FOOTER — Append Before Sending

1. Read `worldcup2026/user_favorites.json`. If it does not exist, create it from `references/tpl_user_favorites.json`.
2. For each flag below that is `false` (or missing), append the line under a `---` separator at the bottom. Each line on its own line, blank line between items, no bullet points:

| Flag is `false` | Append this line |
|-----------------|------------------|
| `features_activated.predictions` | `🎯 **Predictions:** Reply with a scoreline (e.g., "Mexico 2-1") to start your prediction streak!` |
| `features_activated.digest` | `📰 **Daily Digest:** Reply with your favorite teams and players to get a personalized digest every morning.` |
| `features_activated.video` | `🎬 **AI Video:** Reply "make a video of [Player/Team]" to generate a cinematic clip.` |

3. When a feature is successfully used, update `worldcup2026/user_favorites.json` to set that flag to `true` immediately.
4. Missing file or missing key = show the footer line for that feature.

## Step 1: Tool Discovery
**Before attempting generation, run this discovery script to identify available video tools.**

> **IMPORTANT:** Always write the Python script to a `.py` file first, then execute it. Heredoc syntax (`python3 << 'EOF'`) fails in `/bin/sh` due to parenthesis parsing. Use this pattern:
> 1. Write script to temp file: `write_file` → `/tmp/gen_video.py`
> 2. Execute: `python3 /tmp/gen_video.py`
> 3. Clean up if needed

```python
import importlib
import subprocess

available_tools = []

# 1. Check DashScope (Wanx/Alibaba)
try:
    importlib.import_module('dashscope')
    available_tools.append("dashscope")
except ImportError:
    pass

# 2. Check OpenAI (Sora/DALL-E Video)
try:
    importlib.import_module('openai')
    available_tools.append("openai")
except ImportError:
    pass

# 3. Check Replicate (Stable Video/ModelScope)
try:
    importlib.import_module('replicate')
    available_tools.append("replicate")
except ImportError:
    pass

# 4. Check Stability AI (SVD)
try:
    importlib.import_module('stability_sdk')
    available_tools.append("stability")
except ImportError:
    pass

# 5. Check FFmpeg (CLI)
try:
    subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    available_tools.append("ffmpeg")
except FileNotFoundError:
    pass

print(f"Available video tools: {available_tools}")
```

## Step 2: Select Engine
Based on the discovery results, use the **first available tool** from this priority list:

### A. DashScope (Wanx)
*Requires `DASHSCOPE_API_KEY`*
```python
from dashscope import VideoSynthesis
import time, urllib.request

def generate(prompt):
    response = VideoSynthesis.call(model='wan2.6-t2v', prompt=prompt, size='1280*720', prompt_extend=True)
    if response.status_code == 200:
        task_id = response.output.task_id
        while True:
            res = VideoSynthesis.fetch(task_id)
            if res.output.task_status in ('SUCCEEDED', 'FAILED'): break
            time.sleep(5)
        if res.output.task_status == 'SUCCEEDED':
            fname = f"wc_{int(time.time())}.mp4"
            urllib.request.urlretrieve(res.output.video_url, fname)
            return fname
    return None
```

### B. OpenAI (Sora/Video)
*Requires `OPENAI_API_KEY`*
```python
from openai import OpenAI
import time

def generate(prompt):
    client = OpenAI()
    response = client.videos.generate(model="sora-1", prompt=prompt, quality="high")
    # Note: Implementation varies by API version. If URL returned, download it.
    # Example placeholder logic:
    return response.data[0].url 
```

### C. Replicate
*Requires `REPLICATE_API_TOKEN`*
```python
import replicate

def generate(prompt):
    output = replicate.run(
        "stability-ai/stable-video-diffusion:3f0457e4619daac51203dedb472816f3afc54c47685d11689405242979606545",
        input={"prompt": prompt}
    )
    # Returns iterator/generator or list of URLs
    return output
```

### D. Fallback
If **NO tools** are found, report to the user:
> "⚠️ No video generation engines (DashScope, OpenAI, Replicate, etc.) are installed in this environment. Please install `dashscope` or `openai` via `pip` and set the required API keys to generate videos."

## Step 3: Prompt Construction
Enhance the user's prompt before sending to the engine:
1.  **Context:** Add "FIFA World Cup 2026", "stadium atmosphere", "crowd cheering".
2.  **Visuals:** Add specific jersey colors if teams are mentioned.
3.  **Style:** "Cinematic sports broadcast, 4k, realistic motion".
4.  **Safety:** Remove any copyrighted logos if the tool blocks them (describe them abstractly).

## 📤 Output Format

**If the user requested a video:**

```markdown
## 🎬 Generating World Cup Video

> **Scene:** [Description]
> **Engine:** [Tool Name Detected]

*Stand by, generation takes ~30-60 seconds...*
```

**After Generation:**
1.  **Mark as Active:** Update `worldcup2026/user_favorites.json` (`worldcup2026/` under workspace root) by setting `"features_activated.video": true`.
2.  Show the video using `view_video`.
