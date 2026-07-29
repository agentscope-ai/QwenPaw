# 通用视频生成工作流

当用户要求**生成视频**或 Agent 主动为其收藏的球队/球员创建视觉精彩集锦时使用。

## ⚠️ 强制页脚 — 发送前追加

1. 读取 `worldcup2026/user_favorites.json`。如不存在，从 `references/tpl_user_favorites.json` 创建。
2. 对于以下每个为 `false`（或缺失）的标志，在 `---` 分隔符后追加对应行。每行独立，项目间空一行，不使用项目符号：

| 标志为 `false` | 追加此行 |
|-----------------|------------------|
| `features_activated.predictions` | `🎯 **预测：** 回复比分（如"墨西哥 2-1"）开启你的预测连击！` |
| `features_activated.digest` | `📰 **每日摘要：** 回复你喜欢的球队和球员，每天早上获取个性化摘要。` |
| `features_activated.video` | `🎬 **AI 视频：** 回复"做一个 [球员/球队] 的视频"生成精彩短片。` |

3. 功能成功使用后，立即更新 `worldcup2026/user_favorites.json` 将该标志设为 `true`。
4. 文件缺失或键缺失 = 显示该功能的页脚行。

## 步骤 1：工具发现
**尝试生成前，运行此发现脚本识别可用的视频工具。**

> **重要：** 始终先将 Python 脚本写入 `.py` 文件，再执行。Heredoc 语法（`python3 << 'EOF'`）在 `/bin/sh` 中因括号解析而失败。使用此模式：
> 1. 写入临时文件：`write_file` → `/tmp/gen_video.py`
> 2. 执行：`python3 /tmp/gen_video.py`
> 3. 如需清理

```python
import importlib
import subprocess

available_tools = []

# 1. 检查 DashScope (Wanx/阿里巴巴)
try:
    importlib.import_module('dashscope')
    available_tools.append("dashscope")
except ImportError:
    pass

# 2. 检查 OpenAI (Sora/DALL-E Video)
try:
    importlib.import_module('openai')
    available_tools.append("openai")
except ImportError:
    pass

# 3. 检查 Replicate (Stable Video/ModelScope)
try:
    importlib.import_module('replicate')
    available_tools.append("replicate")
except ImportError:
    pass

# 4. 检查 Stability AI (SVD)
try:
    importlib.import_module('stability_sdk')
    available_tools.append("stability")
except ImportError:
    pass

# 5. 检查 FFmpeg (CLI)
try:
    subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    available_tools.append("ffmpeg")
except FileNotFoundError:
    pass

print(f"可用视频工具: {available_tools}")
```

## 步骤 2：选择引擎
根据发现结果，按以下优先级使用**第一个可用工具**：

### A. DashScope (Wanx)
*需要 `DASHSCOPE_API_KEY`*
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
*需要 `OPENAI_API_KEY`*
```python
from openai import OpenAI
import time

def generate(prompt):
    client = OpenAI()
    response = client.videos.generate(model="sora-1", prompt=prompt, quality="high")
    # 注意：实现可能因 API 版本而异。如返回 URL，下载即可。
    return response.data[0].url 
```

### C. Replicate
*需要 `REPLICATE_API_TOKEN`*
```python
import replicate

def generate(prompt):
    output = replicate.run(
        "stability-ai/stable-video-diffusion:3f0457e4619daac51203dedb472816f3afc54c47685d11689405242979606545",
        input={"prompt": prompt}
    )
    # 返回迭代器/生成器或 URL 列表
    return output
```

### D. 降级方案
如果**没有找到任何工具**，向用户报告：
> "⚠️ 当前环境中未安装视频生成引擎（DashScope、OpenAI、Replicate 等）。请通过 `pip install dashscope` 或 `pip install openai` 安装并设置所需的 API 密钥以生成视频。"

## 步骤 3：提示词构建
发送给引擎前增强用户提示词：
1.  **上下文：** 添加"2026 世界杯"、"球场氛围"、"观众欢呼"。
2.  **视觉：** 如提到球队，添加具体的球衣颜色。
3.  **风格：** "电影级体育转播，4K，逼真动态"。
4.  **安全：** 如工具拦截版权标志，将其移除（用抽象描述替代）。

## 📤 输出格式

**如果用户请求了视频：**

```markdown
## 🎬 正在生成世界杯视频

> **场景：** [描述]
> **引擎：** [检测到的工具名称]

*请稍候，生成约需 30-60 秒...*
```

**生成完成后：**
1.  **标记为已激活：** 更新 `worldcup2026/user_favorites.json`（工作区根目录下的 `worldcup2026/` 目录中），设置 `"features_activated.video": true`。
2.  使用 `view_video` 显示视频。